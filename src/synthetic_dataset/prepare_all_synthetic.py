import sys
from collections import defaultdict
from os import makedirs
from os.path import exists, join
from pathlib import Path

import numpy as np
import yaml
from tqdm import tqdm

#
# DISCLAIMER:
# The values for this dataset preparation are hardcoded for our set of generated synthetic spectra and will malfunction
# when used with any other dataset. Mineral ids, total number of minerals, split indices need to be adjusted.
#

# Situation: generated 352,692 synthetic mineral spectra
# Distribution minerals: {11: 29500, 19: 29500, 26: 29500, 28: 29500, 35: 29500, 41: 29500, 73: 29500, 80: 29453, 86: 29365, 88: 29210, 97: 29137, 98: 29027}
# Distribution configs: {0: 70575, 1: 70565, 2: 70541, 3: 70512, 4: 70499}
# will set aside 2x 15% of each mineral for eval and test, and discard 500 samples to work with even 29,000 for all

if __name__ == '__main__':
    with open('config/datasets.yaml') as cnf:
        dataset_configs = yaml.safe_load(cnf)
        try:
            raw_path = dataset_configs['raw_path']
        except KeyError as e:
            print(f'Missing dataset config key: {e}')
            sys.exit(1)

    data_path = join(raw_path, 'synthetic')
    # one key-entry for each mineral id, a defaultdict of lists as value to collect different configurations per mineral
    # result is a dictionary of filenames per mineral id and config
    data = {m_id : defaultdict(list) for m_id in [11, 19, 26, 28, 35, 41, 73, 80, 86, 88, 97, 98]}
    for data_file in tqdm(Path(data_path).rglob('*npy'), total=352692, unit_scale=True, desc='all  '):
        info = data_file.name.split('_')
        id = int(info[3])
        conf = int(info[6])
        data[id][conf].append(data_file)

    # split up collected files evenly (minerals and configs) into train, eval and test sets
    train, eva, test = list(), list(), list()
    # manual 70:15:15 split indices
    slices = [(0, 870, test, 'test '), (870, 1740, eva, 'eval '), (1740, 5800, train, 'train')]
    for sl1, sl2, lst, name in slices:
        for k in tqdm(data.keys(), desc=name, unit_scale=True):
            for v in sorted(data[k].values()):
                lst.extend(v[sl1:sl2])

    files_to_delete = list()
    relabel_dict = {m_id : [0]*5 for m_id in [11, 19, 26, 28, 35, 41, 73, 80, 86, 88, 97, 98]}
    # remove worker_thread-id designation from filename and move it into split folder
    for lst, split in [(sorted(test),'test'), (sorted(eva),'eval'), (sorted(train),'train')]:
        for file_obj in tqdm(lst, desc='cp_'+split, unit_scale=True):
            # grab info to construct new filename and path
            info = str(file_obj.name).split('_')
            m_id = int(info[3])
            conf = int(info[6])
            new_nr = relabel_dict[m_id][conf]
            new_name = '{}_{:05}'.format('_'.join(info[3:-1]), int(new_nr))
            dest_dir = join(data_path, split)

            makedirs(dest_dir, exist_ok=True)
            dest = join(dest_dir, new_name)

            # convert to npz and store at destination
            data, labels = np.load(file_obj, allow_pickle=True)
            # previously copied, now saved as .npz at target location
            np.savez_compressed(dest, data=data, labels=labels)
            relabel_dict[m_id][conf] += 1
            files_to_delete.append(str(file_obj))

    # holds filenames of files that have been used for creating the dataset (process skips ~2,700 files)
    # if drive capacity is low, you can delete all filenames mentioned in this file
    with open(join(raw_path, 'files_to_delete.txt'), 'w') as f:
        for i in files_to_delete:
            f.write(f'{i}\n')
