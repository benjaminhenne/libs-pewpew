import argparse

from sklearn.metrics import balanced_accuracy_score
from tensorflow.keras import Model
from tensorflow.keras.layers import Dense
from tensorflow.keras.utils import plot_model

from utils import (build_model, diagnose_output, prepare_dataset,
                   print_dataset_info, repeat_and_collate,
                   set_classification_targets)


def classify(**args):
    """
    Main method that prepares dataset, builds model, executes training and displays results.
    
    :param args: keyword arguments passed from cli parser
    """
    # only allow print-outs if execution has no repetitions
    allow_print = args['repetitions'] == 1
    # determine classification targets and parameters to construct datasets properly
    cls_target, cls_str = set_classification_targets(args['cls_choice'])
    d = prepare_dataset(
        0,
        cls_target,
        args['batch_size'])

    print('\n\tTask: Classify «{}» using «{}»'.format(cls_str, d['data_str']))
    print_dataset_info(d)

    model = build_model(0, d['num_classes'], name='baseline_mlp', new_input=True)
    model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])

    # train and evaluate - pre-transfer
    model.fit(
        d['train_data'],
        steps_per_epoch=d['train_steps'],
        epochs=args['epochs'],
        verbose=1,
        class_weight=d['class_weights'])
    print('Evaluate ...')
    model.evaluate(d['eval_data'], steps=d['test_steps'], verbose=1)

    del d
    d = prepare_dataset(
        2,
        cls_target,
        args['batch_size'])
    print_dataset_info(d)

    # make layers untrainable and remove classification layer, then train new last layer on handheld data
    for l in model.layers[:-1]:
        l.trainable = False
    
    if allow_print:
        plot_model(model, to_file='img/transfer_mlp_pre.png')

    new_layer = Dense(d['num_classes'], activation='softmax', name='dense_transfer')(model.layers[-2].output)
    model = Model(inputs=model.inputs, outputs=new_layer, name='transfer_model')
    model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])

    if allow_print:
        model.summary()
        print('')
        plot_model(model, to_file='img/transfer_mlp_post.png')

    # train and evaluate - post-transfer
    model.fit(
        d['train_data'],
        steps_per_epoch=d['train_steps'],
        epochs=args['epochs'],
        verbose=1,
        class_weight=d['class_weights'])
    print('Evaluate ...')
    model.evaluate(d['eval_data'], steps=d['test_steps'], verbose=1)

    # predict on testset and calculate classification report and confusion matrix for diagnosis
    print('Test ...')
    pred = model.predict(d['test_data'], steps=d['test_steps'])

    if allow_print:
        diagnose_output(d['test_labels'], pred.argmax(axis=1), d['classes_trans'])
    
    return balanced_accuracy_score(d['test_labels'], pred.argmax(axis=1))


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
        default=1,
        help='Which dataset(s) to use. 0=synthetic, 1=hh_6, 2=hh_12, 3=hh_all',
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
    args = parser.parse_args()

    repeat_and_collate(classify, **vars(args))
