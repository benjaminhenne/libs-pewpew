import argparse

from tensorflow.keras import Model
from tensorflow.keras.layers import Input, Maximum
from tensorflow.keras.utils import plot_model

from utils import (build_model, diagnose_output, prepare_dataset,
                   print_dataset_info, set_classification_targets)

def classify(**args):
    """
    Main method that prepares dataset, builds model, executes training and displays results.
    
    :param args: keyword arguments passed from cli parser
    """
    batch_size = 64
    # determine classification targets and parameters to construct datasets properly
    cls_target, cls_str = set_classification_targets(args['cls_choice'])
    d = prepare_dataset(args['dataset_choice'], cls_target, batch_size)

    print('\n\tTask: Classify «{}» using «{}»\n'.format(cls_str, d['data_str']))
    print_dataset_info(d)

    # build and train
    models = list()
    inputs = Input(shape=(7810,))
    for i in range(args['num_models']):
        print(f'\nTrain model {i+1} ...')
        model = build_model(i, d['num_classes'], inputs=inputs)
        model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])
        model.fit(
            d['train_data'],
            steps_per_epoch=d['train_steps'],
            epochs=args['epochs'],
            verbose=1,
            class_weight=d['class_weights'])
        models.append(model)

    # combine outputs of all previous models, treat outputs
    multi_output = [m.outputs[0] for m in models]
    y = Maximum()(multi_output)
    model = Model(inputs, outputs=y, name='ensemble')
    plot_model(model, to_file='img/ensemble_mlp.png')

    # compile and evaluation model
    print('Evaluate ...')
    model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])
    model.evaluate(d['eval_data'], steps=d['test_steps'], verbose=1)

    # predict on testset and calculate classification report and confusion matrix for diagnosis
    print('Test ...')
    pred = model.predict(d['test_data'], steps=d['test_steps'])

    diagnose_output(d['test_labels'], pred.argmax(axis=1), d['classes_trans'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
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
    parser.add_argument(
        '-m', '--models',
        type=int,
        default=4,
        help='How many models the ensemble should use',
        dest='num_models'
    )
    args = parser.parse_args()

    classify(**vars(args))
