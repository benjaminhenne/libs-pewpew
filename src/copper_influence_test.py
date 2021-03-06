import argparse

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sn
from sklearn.metrics import (balanced_accuracy_score, classification_report,
                             confusion_matrix, precision_score, recall_score)
from sklearn.utils import class_weight
from tqdm import tqdm

from utils import (build_model, prepare_dataset, repeat_and_collate,
                   set_classification_targets)


def classify(**args):
    """
    Main method that prepares dataset, builds model, executes training and displays results.

    :param args: keyword arguments passed from cli parser
    """


    # determine classification targets and parameters to construct datasets properly
    cls_target, cls_str = set_classification_targets(args['cls_choice'])

    overall_res = list()
    for amount_t in [.1, .4, .9]:
        print('Amount t: ', amount_t, '\n')
        res_per_amount = list()
        for drop_t in [.1, .4, .9]:
            print('Drop t: ',drop_t, '\n')
            d = prepare_dataset(
                args['dataset_choice'],
                cls_target,
                args['batch_size'],
                args['norm_choice'],
                amount_t,
                drop_t)
                
            if len(d['train_labels']) == 0 or len(np.unique(d['train_labels'])) != 12:
                print('not enough data')
                res_per_amount.append(0.)
                continue

            model = build_model(0, d['num_classes'], name='baseline_mlp', new_input=True)
            model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])

            # callback to log data for TensorBoard
            # tb_callback = TensorBoard(log_dir='./results', histogram_freq=0, write_graph=True, write_images=True)

            # train and evaluate
            model.fit(
                d['train_data'],
                steps_per_epoch=d['train_steps'],
                epochs=args['epochs'],
                # callbacks=[tb_callback],
                verbose=1,
                class_weight=d['class_weights'])

            model.evaluate(d['eval_data'], steps=d['test_steps'], verbose=1)

            # predict on testset and calculate classification report and confusion matrix for diagnosis
            pred = model.predict(d['test_data'], steps=d['test_steps'])

            print('Accuracy: ', balanced_accuracy_score(d['test_labels'], pred.argmax(axis=1)))
            res = [balanced_accuracy_score(d['test_labels'], pred.argmax(axis=1))]#, precision_score(
                # test_labels, pred, average='samples'), recall_score(test_labels, pred, average='samples')]
            res_per_amount.append(res)

        overall_res.append(res_per_amount)

    l = [.1, .4, .9]
    for i in range(len(overall_res)):
        for j in range(len(overall_res[0])):
            print(f'{l[i]:3}\t{l[j]:3}\t{overall_res[i][j]}')
        print(overall_res)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-r', '--repetitions',
        type=int,
        default=1,
        help='Number of times to repeat experiment',
        dest='repetitions'
    )
    parser.add_argument(
        '-b', '--batchsize',
        type=int,
        default=64,
        help='Target batch size of dataset preprocessing',
        dest='batch_size'
    )
    parser.add_argument(
        '-d', '--dataset',
        type=int,
        default=2,
        help='Which dataset(s) to use. 0=synthetic, 1=hh_12, 2=hh_all',
        dest='dataset_choice'
    )
    parser.add_argument(
        '-c', '--classification',
        type=int,
        default=2,
        help='Which classification target to pursue. 0=classes, 1=subgroups, 2=minerals',
        dest='cls_choice'
    )
    parser.add_argument(
        '-e', '--epochs',
        type=int,
        default=5,
        help='How many epochs to train for',
        dest='epochs'
    )
    parser.add_argument(
        '-n', '--normalisation',
        type=int,
        default=2,
        help='Which normalisation to use. 0=None, 1=snv, 2=minmax',
        dest='norm_choice'
    )

    args = parser.parse_args()

    repeat_and_collate(classify, **vars(args))
