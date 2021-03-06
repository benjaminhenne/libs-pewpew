import sys
import warnings
from functools import partial
from glob import glob
from math import ceil
from ntpath import basename
from os import makedirs, sep
from os.path import join

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sn
import tensorflow as tf
import yaml
from keras.utils import to_categorical
from scipy import sparse
from scipy.sparse.linalg import spsolve
from sklearn.metrics import (balanced_accuracy_score, classification_report,
                             confusion_matrix)
from sklearn.utils import class_weight, shuffle
from tensorflow.keras import Model, regularizers
from tensorflow.keras.layers import Concatenate, Dense, Dropout, Input
from tqdm import tqdm


def repeat_and_collate(classify_fn, **args):
    """
    Repeats classification function call with provided command-line arguments, collects results and prints mean and std.

    :param classify_fn: classification function reference
    :param args: keyword-argument dictionary of command-line parameters provided by argparse
    """
    results = [classify_fn(**args) for _ in range(args['repetitions'])]

    if len(results) > 1:
        print('\nResults of experiment:')
        for i,iteration in enumerate(results):
            print(f'Run {i+1:02d} balanced accuracy:\t{round(results[i], 5)}')
        print(f'Average balanced accuracy:\t{round(np.mean(results), 5)} (\u00B1 {round(np.std(results), 5)})\n')


def has_sufficient_copper(spectrum, amount_t=0.5, drop_t=0.3):
    """
    Checks individual spectras for their copper content. If more than *amount_t*% of copper lines are below the *drop_t*
    percentile, then the spectrum more likely captures matrix rock.

    :param spectrum:    ndarray containing the spectrum
    :param amount_t:    threshold (float %) of copper lines expected to have high intensity
    :param drop_t:      threshold (float %) signifying "low" copper intensity
    :returns: True if the spectrum contains more than the specified amount of copper, False otherwise
    """
    # lookup for position of wavelength in input data
    copper_lines_indices = [int(round(cpl - 180, 1) * 10) for cpl in [219.25, 224.26, 224.7, 324.75, 327.4, 465.1124, 510.55, 515.32, 521.82]]
    low_copper_sum = 0
    for cli in copper_lines_indices:
        # find position in data from wavelength. 219.25 -> 219.2 -> 39.2 -> data[392] == [219.2, ...]
        if spectrum[cli] < drop_t:
            low_copper_sum += 1
        if (low_copper_sum / len(copper_lines_indices)) > amount_t:
            return False
    return True


def set_classification_targets(cls_choice):
    """
    Validate classification choice by user and provide written detail about what the goal of the classification effort is.

    :param cls_choice: Classification choice provided by user (via cli parameter)
    :returns: tuple of (classification choice, classification string)
    :raise ValueError: cls_choice is out of defined range
    """
    if cls_choice == 0:
        cls_str = 'mineral classes'
    elif cls_choice == 1:
        cls_str = 'mineral subgroups'
    elif cls_choice == 2:
        cls_str = 'minerals'
    else:
        raise ValueError('Invalid classification target parameter')
    return cls_choice, cls_str


def __get_labels(files, targets):
    """
    Extracts data labels from filenames of passed list of filepaths. Faster than loading all files into memory. Only
    provides labels for current classification target.

    :param files:       list of file paths
    :param targets:     classification targets
    :returns:           ndarray(int) of labels
    :raises error type: raises description
    """
    # translates targets into position of information in filename
    target_indices = [1, 2, 0]
    return np.array([int(basename(f).split('_')[target_indices[targets]]) for f in files], dtype=int)


def get_transformation_dict(labels, dict_or_np='dict'):
    """
    Creates gapless list of labels (e.g. 0, 1, 2, 3, 4) from "sparse" data labels (e.g. 11, 28, 35, 73, 98).

    :param labels:      list of labels to transform
    :param dict_or_np:  {'dict', 'np', 'numpy'} whether returned transformation matrix should be a dict or ndarray
    :returns:           label transformation info, as dict or ndarray
    """
    trans_dict = {unique_label : i for i, unique_label in enumerate(np.unique(labels))}
    if dict_or_np == 'np' or dict_or_np == 'numpy':
        trans_dict = np.array([trans_dict[i] if i in trans_dict.keys() else 0 for i in range(np.max(np.unique(labels))+1)])
    return trans_dict


def transform_labels(label_data, trans_dict):
    """
    Transforms labels according to information from trans_dict.

    :param label_data:  labels to transform
    :param trans_dict:  transformation info, as dict or ndarray
    :returns:           list of transformed labels
    """
    if isinstance(label_data, (list, np.ndarray)):
        return np.array([trans_dict[l] for l in label_data])
    else:
        return trans_dict[label_data]


def normalise_minmax(sample):
    """
    Normalises single sample according to minmax. Also strips wavelength information from sample.
    Adapted from Federico Malerba.

    :param sample:  sample to process
    :returns:       normalised sample
    """
    if np.max(sample) > 0:
        return sample / np.max(sample)
    else:
        print('Sample is empty')


def normalise_snv(sample):
    """
    Standard normal variate (SNV) normalisation

    :param sample:  sample to process
    :returns:       normalised sample
    """
    if np.max(sample) > 0:
        return (sample - np.mean(sample)) / np.std(sample)
    else:
        print('Sample is empty')


def no_normalisation(sample):
    """
    No normalisation, just strips wavelength information from sample.

    :param sample:  sample to process
    :returns:       not normalised sample
    """
    return sample


def baseline_als_optimized(y, lam=102, p=0.1, niter=10):
    """
    Calculates the baseline correction of LIBS spectra and returns corrected
    spectra.
    :param y:       sample to process
    :param lam:     smoothness
    :param p:       asymmetry
    :param niter:   number of iterations
    """
    if np.max(y) <0:
        warnings.warn('LIBS shot is empty or invalid, no positive values')
    y = y[:,1].clip(min=0) #remove values < 0 and discard wavelengths
    L = len(y)
    D = sparse.diags([1,-2,1],[0,-1,-2], shape=(L,L-2))
    D = lam * D.dot(D.transpose()) # Precompute this term since it does not depend on `w`
    w = np.ones(L)
    W = sparse.spdiags(w, 0, L, L)
    for i in range(niter):
        W.setdiag(w) # Do not create a new matrix, just update diagonal values
        Z = W + D
        z = spsolve(Z, w*y)
        w = p * (y > z) + (1-p) * (y < z)
    new = y - z
    return new.clip(min=0)


def diagnose_output(y_true, y_pred, class_ids, show=True, file_name=None):
    """
    Calculates sklearn.metrics.classification_report, balanced accuracy score and confusion matrix for provided data and 
    visualises them.

    :param y_true:      true label information
    :param y_pred:      predicted values
    :param class_ids:   transformed ids of classes for plotting
    """
    print(classification_report(y_true, y_pred, labels=class_ids))
    print(f'Balanced accuracy score: {balanced_accuracy_score(y_true=y_true, y_pred=y_pred)}')

    # normalised confusion matrix
    matrix = confusion_matrix(y_true, y_pred, labels=class_ids)
    matrix = matrix.astype('float') / matrix.sum(axis=1)[:, np.newaxis]

    fig = plt.figure(figsize = (10,7))
    sn.heatmap(matrix, annot=True, fmt='.2f') # xticklabels=target_names, yticklabels=target_names)
    plt.gca().tick_params(axis='y', rotation=45)
    plt.title('Confusion matrix (normalised)')
    plt.xlabel('Predicted label')
    plt.ylabel('True label')
    if show:
        plt.show()
    else:
        plt.savefig(join('results', f'{file_name}.pdf'), bbox_inches='tight')
        plt.close(fig)


def get_64shot_transition_matrix(test_filepaths):
    """
    Takes the file paths of the test set and computes a transition matrix from a ordered, consecutive list of file paths
    to a stack of 8x8 grid layouts. Because the majority of real handheld data has one or more gaps somewhere in its 64
    shots, just piling all results consecutively into a 8x8 grid does not work and these gaps need to be taken into
    account.

    :param test_data_path: list of file paths
    :returns: ndarray [measure_point, x_coord, y_coord] of transitions from consecutive list to heatmap layout
    """
    i = 0
    measure_point_split = list()
    # iterate over all files (sorted alphabetically)
    while i < len(test_filepaths):
        # extract id and measure point
        m_id, _, _, measure_point, _ = test_filepaths[i].split(sep)[-1].split('_')
        split = list()
        # look ahead for all other files of same measure point
        # save them to list of mps, then continue iterating after last current sample of mp
        # reduces runtime to O(n) instead of O(n²)
        for j in range(i, len(test_filepaths)):
            m_id_j, _, _, mp_j, _ = test_filepaths[j].split(sep)[-1].split('_')
            if m_id == m_id_j and measure_point == mp_j:
                split.append(test_filepaths[j])
                i += 1
            else: # files are sorted, assumes measure point is exhausted after first mismatch
                break
        measure_point_split.append(split)

    # len(files) x [measure_point x_coord y_coord]
    transition_matrix = np.zeros((len(test_filepaths), 3), dtype=int)
    i = 0
    j = 0

    # create transition for each shot onto 8x8 grid, to plot a heatmap of LIBS accuracy
    for mp in measure_point_split:
        for sample in mp:
            # string clipping of Shot-ID from filename, -1 to make it work with 0-based math
            shot_id = int(sample.split('/')[-1].split('_')[-1][:-4]) - 1
            transition_matrix[i, 0] = j
            transition_matrix[i, 1] = shot_id // 8
            transition_matrix[i, 2] = shot_id % 8
            i += 1
        j += 1

    return transition_matrix


def compute_accuracy_heatmaps(d, target_preds, cls_target, epochs):
    """
    Create 8x8 grid accuracy heatmaps using model predictions and the data transition matrices of the datasets. These
    matrices detail where on the 8x8 grid each data sample will be placed. This needs special attention because gaps in
    the original shot files need to be accounted for.

    :param d: Dataset container holding all information from samples, names, class weights to transition information
    :param target_preds: Model predictions, but reduced to the predicted value of just the correct label
    :param cls_target: which classification target to pursue, same as the ones used by the model
    :param epochs: how many epochs the model ran for, only used to name the save directory
    """
    # empty ndarray with max measurepoints +1 space for 8x8 grids
    acc_heatmap = np.zeros((np.max(d['heatmap_tm'], axis=0)[0] + 1, 8, 8))

    # use heatmap transition matrix to build 8x8 grid for each measure point
    # necessary because sometimes shots are missing in between or at the end of measure points
    for i, single_pred in enumerate(target_preds):
        acc_heatmap[d['heatmap_tm'][i][0], d['heatmap_tm'][i][1], d['heatmap_tm'][i][2]] = single_pred

    # info for titles and save directory
    target_str = 'Classes' if cls_target == 0 else ('Subgroups' if cls_target == 1 else 'Minerals')
    dest_dir = d['dataset_name'] + f'_c{cls_target}_e' + str(epochs) + '_64heatmap'
    dest_path = join('results', dest_dir)
    makedirs(dest_path, exist_ok=True)

    # create heatmap image out of 8x8 grid for each measure point
    for i,m in tqdm(enumerate(acc_heatmap), desc='heatmap_plt', total=len(acc_heatmap)):
        fig = plt.figure(figsize = (10,7))
        sn.heatmap(m, annot=True, fmt='.2f')
        plt.gca().tick_params(axis='y', rotation=45)
        plt.title(f'Per shot accuracy of a single measure point (No. {i}), Target: {target_str}')
        plt.savefig(join(dest_path, f'mp_{i:03}.pdf'), bbox_inches='tight')
        plt.close(fig) # needs to be closed, otherwise 100 image panels will pop up next time plt.show() is called

    # average over all results
    mean_heatmap = np.mean(acc_heatmap, axis=0)

    plt.figure(figsize = (10,7))
    sn.heatmap(mean_heatmap, annot=True, fmt='.2f')
    plt.gca().tick_params(axis='y', rotation=45)
    plt.title(f'Per shot accuracy, mean over all measure points, Target: {target_str}')
    dataset_name = d['dataset_name']
    plt.savefig(join(dest_path, f'{dataset_name}_c{cls_target}.pdf'), bbox_inches='tight')
    plt.show()

    np.save(join(dest_path, f'{dataset_name}_c{cls_target}.npy'), acc_heatmap)


def __data_generator(files, targets, num_classes, batch_size, trans_dict, shuffle_and_repeat, norm_function, categorical=True):
    """
    Internal generator function to yield processed batches of data.

    :param files:               list of files to work with
    :param targets:             classification targets chosen by user
    :param num_classes:         number of unique classes in dataset
    :param batch_size:          batch size of yielded batches
    :param trans_dict:          transformation info to process labels
    :param shuffle_and_repeat:  True to shuffle and repeat dataset infinitely, False otherwise
    :param norm_function:       chosen normalisation function
    :param categorical:         True to provide categorical labels, False otherwise
    :yields:                    (sample, label) tuples
    """
    i = 0
    run = True
    files = shuffle(files) if shuffle_and_repeat else files
    while run:
        # samples: 7810 data points per file, labels: num_classes size of categorical labels
        samples = np.zeros((batch_size, 7810), dtype='float64')
        labels = np.zeros((batch_size, num_classes), dtype=int) if categorical else np.zeros((batch_size,), dtype=int)
        # read in batch_size many np files
        for j in range(batch_size):
            # after all files have been consumed
            if i >= len(files):
                if shuffle_and_repeat:
                    i = 0
                    files = shuffle(files)
                else:
                    run = False
                    samples, labels = samples[:j], labels[:j]
                    break

            # load data, all:(data:(7810, 2), labels:(3,))
            with np.load(files[i]) as npz_file:
                label = transform_labels(npz_file['labels'][targets], trans_dict)
                labels[j]  = to_categorical(label, num_classes) if categorical else label
                # discard wavelength dimension from here on, only work with intensity [:,1]
                samples[j] = norm_function(npz_file['data'][:,1])

            i += 1
        yield samples, labels


def prepare_dataset(dataset_choice, target, batch_size, normalisation=2, train_shuffle_repeat=True, categorical_labels=True, mp_heatmap=False):
    """
    Provides data generators, labels and other information for selected dataset.

    :param dataset_choice:          which dataset to prepare
    :param targets:                 classification target
    :param batch_size:              batch size
    :param normalisation:           which normalisation method to use
    :param train_shuffle_repeat:    whether to shuffle and repeat the train generator
    :param categorical_labels:      whether to transform labels to categorical
    :param mp_heatmap:              whether to include a transition matrix for 64-Shot heatmap analyses
    :returns:                       dict containing train/eval/test generators, train/test labels, number of unique
                                    classes, original and transformed class ids, train/test steps, balanced class
                                    weights and data description
    :raises ValueError:             if dataset_choice is invalid
    """
    with open('config/datasets.yaml') as cnf:
        dataset_configs = yaml.safe_load(cnf)
        try:
            if dataset_choice == 0:
                data_path = dataset_configs['synth_path']
                data_str = dataset_configs['synth_str']
                data_name = dataset_configs['synth_name']
            elif dataset_choice == 1:
                data_path = dataset_configs['hh_12_path']
                data_str = dataset_configs['hh_12_str']
                data_name = dataset_configs['hh_12_name']
            elif dataset_choice == 2:
                data_path = dataset_configs['hh_all_path']
                data_str = dataset_configs['hh_all_str']
                data_name = dataset_configs['hh_all_name']
            else:
                raise ValueError('Invalid dataset parameter passed to prepare_dataset.')
        except KeyError as e:
            print(f'Missing dataset config key: {e}')
            sys.exit(1)

    if normalisation == 0:
        norm_function = no_normalisation
    elif normalisation == 1:
        norm_function = normalise_snv
    elif normalisation == 2:
        norm_function = normalise_minmax

    train_data = sorted(glob(join(data_path, 'train', '*.npz')))
    test_data = sorted(glob(join(data_path, 'test', '*.npz')))

    train_labels = __get_labels(train_data, target)
    test_labels = __get_labels(test_data, target)

    num_classes = len(np.unique(train_labels))
    trans_dict = get_transformation_dict(train_labels)
    class_weights = class_weight.compute_class_weight('balanced', sorted(trans_dict.keys()), train_labels)

    # list of "class" names used for confusion matrices and validity testing. Not always classes, also subgroups or
    # minerals, depending on classification targets
    return {
        'dataset_name' : data_name,
        'train_data'   : __data_generator(train_data, target, num_classes, batch_size, trans_dict, train_shuffle_repeat, norm_function, categorical_labels),
        'eval_data'    : __data_generator(test_data, target, num_classes, batch_size, trans_dict, False, norm_function, categorical_labels),
        'test_data'    : __data_generator(test_data, target, num_classes, batch_size, trans_dict, False, norm_function, categorical_labels),
        'train_labels' : transform_labels(train_labels, trans_dict),
        'test_labels'  : transform_labels(test_labels, trans_dict),
        'batch_size'   : batch_size,
        'num_classes'  : num_classes,
        'norm_function': norm_function.__name__,
        'classes_orig' : sorted(trans_dict.keys()),
        'classes_trans': sorted(trans_dict.values()),
        'train_steps'  : ceil(len(train_labels) / batch_size),
        'test_steps'   : ceil(len(test_labels) / batch_size),
        'class_weights': {i:weight for i, weight in enumerate(class_weights)},
        'heatmap_tm'   : get_64shot_transition_matrix(test_data) if mp_heatmap else None,
        'data_str'     : data_str,
    }


def print_dataset_info(dataset):
    """
    Prints formatted dataset information for visual inspection.

    :param dataset: dict containing dataset information
    """
    print('\n\tData set information:\n\t{')
    for k,v in dataset.items():
        if k == 'heatmap_tm':
            print('\t\t{:<13} : {},'.format(k, 'N/A' if v is None else f'{np.max(v, axis=0)[0] + 1} measure point transitions'))
        elif hasattr(v, '__len__') and not isinstance(v, str):
            print('\t\t{:<13} : {},{}'.format(k, v, f' len({len(v)}),'))
        else:
            print(f'\t\t{k:<13} : {v},')
    print('\t}\n')


def prepare_mixture_dataset(target, batch_size, mixture_pct, normalisation=2):
    """
    Provides data generators, labels and other information for a mixture of synthetic and handheld data. Returns partial
    function calls for eval and test set generators because they are non-repeating, so they can be used multiple times.

    :param dataset_choice:          which dataset to prepare
    :param targets:                 classification target
    :param batch_size:              batch size
    :param mixture_pct:             percentage of dataset mixture to produce
    :returns:                       dict containing train/eval/test generators, train/test labels, number of unique
                                    classes, original and transformed class ids, train/test steps, balanced class
                                    weights and data description
    :raises ValueError:             if dataset_choice is invalid
    """
    with open('config/datasets.yaml') as cnf:
        dataset_configs = yaml.safe_load(cnf)
        try:
            path_hh_12 = dataset_configs['hh_12_path']
            path_synthetic = dataset_configs['synth_path']
        except KeyError as e:
            print(f'Missing dataset config key: {e}')
            sys.exit(1)

    if normalisation == 0:
        norm_function = no_normalisation
    elif normalisation == 1:
        norm_function = normalise_snv
    elif normalisation == 2:
        norm_function = normalise_minmax

    # hh data
    train_data_hh = np.array(sorted(glob(join(path_hh_12, 'train', '*.npz'))))
    test_data_hh = np.array(sorted(glob(join(path_hh_12, 'test', '*.npz'))))
    train_labels_hh = __get_labels(train_data_hh, target)
    test_labels_hh = __get_labels(test_data_hh, target)

    # synthetic data
    train_data_syn = np.array(sorted(glob(join(path_synthetic, 'train', '*.npz'))))
    test_data_syn = np.array(sorted(glob(join(path_synthetic, 'test', '*.npz'))))
    train_labels_syn = __get_labels(train_data_syn, target)
    test_labels_syn = __get_labels(test_data_syn, target)

    # class counts
    hh_counts = dict(zip(*np.unique(train_labels_hh, return_counts=True)))
    syn_counts = dict(zip(*np.unique(train_labels_syn, return_counts=True)))

    # iterate over labels and counts of both hh and synthetic dataset
    for (hhl,hhc),(_,sync) in zip(hh_counts.items(), syn_counts.items()):
        # amount of data to mix in (mixture_pct% of hhc-many data samples)
        n = int(hhc * mixture_pct)
        if n > sync:
            print(f'Warning: Requested amount of data ({n}) for label {hhl} is larger than synthetic data for this label ({sync})')
        # get logical list of indices where synthetic training labels are equal to target label
        # then reduce that list to only the True labels, so we can slice off the required amount of items
        indices = np.where((train_labels_syn == hhl))[0]
        train_data_hh = np.append(train_data_hh, train_data_syn[indices][:n])
        train_labels_hh = np.append(train_labels_hh, train_labels_syn[indices][:n])

    # post dataset consistency check
    # hh_counts_post = dict(zip(*np.unique(train_labels_hh, return_counts=True)))
    # syn_counts_post = dict(zip(*np.unique(train_labels_syn, return_counts=True)))
    # for (hhl1,hhc1),(hhl2,hhc2) in zip(hh_counts_post.items(), hh_counts.items()):
    #     print(f'label: {hhl1}    before: {hhc2:4d}    after: {hhc1:4d}    diff: {hhc1-hhc2:4d} ({round(((hhc1-hhc2)/hhc2)*100,1):4}%)')

    num_classes = len(np.unique(train_labels_hh))
    trans_dict = get_transformation_dict(train_labels_hh)
    class_weights = class_weight.compute_class_weight('balanced', sorted(trans_dict.keys()), train_labels_hh)

    # list of "class" names used for confusion matrices and validity testing. Not always classes, also subgroups or
    # minerals, depending on classification targets
    return {
        'dataset_name' : 'mixture synthetic/hh_12',
        'train_data'   : __data_generator(train_data_hh, target, num_classes, batch_size, trans_dict, True, norm_function),
        'eval_data'    : partial(__data_generator, test_data_hh, target, num_classes, batch_size, trans_dict, False, norm_function),
        'test_data'    : partial(__data_generator, test_data_hh, target, num_classes, batch_size, trans_dict, False, norm_function),
        'train_labels' : transform_labels(train_labels_hh, trans_dict),
        'test_labels'  : transform_labels(test_labels_hh, trans_dict),
        'batch_size'   : batch_size,
        'num_classes'  : num_classes,
        'norm_function': norm_function.__name__,
        'classes_orig' : sorted(trans_dict.keys()),
        'classes_trans': sorted(trans_dict.values()),
        'train_steps'  : ceil(len(train_labels_hh) / batch_size),
        'test_steps'   : ceil(len(test_labels_hh) / batch_size),
        'class_weights': {i:weight for i, weight in enumerate(class_weights)},
        'data_str'     : f'hh_12 data augmented with {mixture_pct*100}% synthetic data',
    }


def build_model(id, num_classes, name='model', inputs=None, new_input=False, reg=regularizers.l2, reg_lambda=0.0001):
    model_name = name if name else f'model_{id}'
    with tf.name_scope(model_name):
        if new_input:
            inputs = Input(shape=(7810,))
        net = Dense(64, activation='relu', kernel_regularizer=reg(reg_lambda))(inputs)
        net = Dropout(0.5)(net)
        net = Dense(256, activation='relu', kernel_regularizer=reg(reg_lambda))(net)
        net = Dropout(0.5)(net)
        net = Dense(256, activation='relu', kernel_regularizer=reg(reg_lambda))(net)
        net = Dense(num_classes, activation='softmax')(net)

    model = Model(inputs=inputs, outputs=net, name=model_name)
    return model

def build_model_concat(id, num_classes, inputs=None, new_input=False, concat_model=None, reg=regularizers.l2, reg_lambda=0.0001):
    model_name = f'model_{id}'
    with tf.name_scope(model_name):
        if new_input:
            inputs = Input(shape=(7810,))
        if concat_model:
            inputs = Concatenate()([concat_model.inputs[0], concat_model.layers[-2].output])
        net = Dense(64, activation='relu', kernel_regularizer=reg(reg_lambda))(inputs)
        net = Dropout(0.5)(net)
        net = Dense(256, activation='relu', kernel_regularizer=reg(reg_lambda))(net)
        net = Dropout(0.5)(net)
        net = Dense(256, activation='relu', kernel_regularizer=reg(reg_lambda))(net)
        net = Dropout(0.5)(net)
        if not concat_model:
            net = Dense(7810, activation='relu', kernel_regularizer=reg(reg_lambda))(net)
        net = Dense(num_classes, activation='softmax')(net)

    if not concat_model:
        model = Model(inputs=inputs, outputs=net, name=model_name)
    else:
        model = Model(inputs=concat_model.inputs[0], outputs=net, name=model_name)
    return model
