import argparse

from sklearn.metrics import balanced_accuracy_score
from tensorflow.keras.callbacks import EarlyStopping, TensorBoard
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
        args['dataset_choice'],
        cls_target,
        args['batch_size'],
        args['norm_choice'])

    print('\n\tTask: Classify «{}» using «{}»\n'.format(cls_str, d['data_str']))
    print_dataset_info(d)

    model = build_model(0, d['num_classes'], name='baseline_mlp', new_input=True)
    model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])
    if allow_print:
        model.summary()
        print('')

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
        choices=[0, 1, 2],
        default=1,
        help='Which dataset(s) to use. 0=synthetic, 1=hh_12, 2=hh_all',
        dest='dataset_choice'
    )
    parser.add_argument(
        '-c', '--classification',
        type=int,
        choices=[0, 1, 2],
        default=2,
        help='Which classification target to pursue. 0=classes, 1=subgroups, 2=minerals',
        dest='cls_choice'
    )
    parser.add_argument(
        '-e', '--epochs',
        type=int,
        default=10,
        help='How many epochs to train for',
        dest='epochs'
    )
    parser.add_argument(
        '-n', '--normalisation',
        type=int,
        choices=[0, 1, 2],
        default=2,
        help='Which normalisation to use. 0=None, 1=snv, 2=minmax',
        dest='norm_choice'
    )

    args = parser.parse_args()

    repeat_and_collate(classify, **vars(args))
