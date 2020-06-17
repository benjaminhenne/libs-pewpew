import numpy as np
import glob
import os
import tqdm

def convert_to_npz(path):
    files = sorted(glob.glob(os.path.join(path,'*.npy')))
    for f in files:
        data, labels = np.load(f, allow_pickle=True)
        filename = f[:-4] # filename without .npy
        np.savez_compressed(filename, data=data, labels=labels)
        os.remove(f) #delete npy file

convert_to_npz('/samba/cjh/julia/synthetic_all/train')
convert_to_npz('/samba/cjh/julia/synthetic_all/test')
convert_to_npz('/samba/cjh/julia/synthetic_all/eval')
