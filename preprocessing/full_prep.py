import os
import warnings

from os import path as p
from functools import partial
from multiprocessing import Pool

import h5py
import numpy as np

from skimage import measure
from skimage.morphology import convex_hull_image
from scipy.io import loadmat
from scipy.ndimage.interpolation import zoom
from scipy.ndimage.morphology import binary_dilation, generate_binary_structure

from step1 import step1_python


def process_mask(mask):
    convex_mask = np.copy(mask)

    for i_layer in range(convex_mask.shape[0]):
        mask1 = np.ascontiguousarray(mask[i_layer])

        if np.sum(mask1) > 0:
            mask2 = convex_hull_image(mask1)

            if np.sum(mask2) > 2 * np.sum(mask1):
                mask2 = mask1
        else:
            mask2 = mask1

        convex_mask[i_layer] = mask2

    struct = generate_binary_structure(3, 1)
    return binary_dilation(convex_mask, structure=struct, iterations=10)


def lumTrans(img):
    lungwin = np.array([-1200., 600.])
    newimg = (img - lungwin[0]) / (lungwin[1] - lungwin[0])
    newimg[newimg < 0] = 0
    newimg[newimg > 1] = 1
    return (newimg * 255).astype('uint8')


def resample(imgs, spacing, new_spacing, order=2):
    if len(imgs.shape) == 3:
        new_shape = np.round(imgs.shape * spacing / new_spacing)
        true_spacing = spacing * imgs.shape / new_shape
        resize_factor = new_shape / imgs.shape

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            imgs = zoom(imgs, resize_factor, mode='nearest', order=order)

        return imgs, true_spacing
    elif len(imgs.shape) == 4:
        n = imgs.shape[-1]
        newimg = []

        for i in range(n):
            slice = imgs[:,:,:,i]
            newslice,true_spacing = resample(slice,spacing,new_spacing)
            newimg.append(newslice)

        newimg = np.transpose(np.array(newimg), [1, 2, 3, 0])
        return newimg, true_spacing
    else:
        raise ValueError('wrong shape')


def savenpy(dirname, prep_folder, data_path, use_existing=True):
    print('saving %s...' % dirname)
    resolution = np.array([1, 1, 1])

    if use_existing:
        label_path = p.join(prep_folder, dirname + '_label.npy')
        clean_path = p.join(prep_folder, dirname + '_clean.npy')
        exists = p.exists(label_path) and p.exists(clean_path)
    else:
        exists = False

    if exists:
        print(dirname + ' already processed')
        processed = 0
    else:
        print(dirname + ' not yet processed')
        case_path = p.join(data_path, dirname)
        im, m1, m2, spacing = step1_python(case_path)
        Mask = m1 + m2

        newshape = np.round(np.array(Mask.shape) * spacing / resolution)
        xx, yy, zz = np.where(Mask)
        box = np.array(
            [
                [np.min(xx), np.max(xx)],
                [np.min(yy), np.max(yy)],
                [np.min(zz), np.max(zz)]])

        box = box * np.expand_dims(spacing,1) / np.expand_dims(resolution, 1)
        box = np.floor(box).astype('int')
        margin = 5
        extendbox = np.vstack(
            [
                np.max([[0, 0, 0], box[:,0] - margin], 0),
                np.min([newshape, box[:,1] + 2 * margin], axis=0).T]).T

        extendbox = extendbox.astype('int')

        convex_mask = m1
        dm1 = process_mask(m1)
        dm2 = process_mask(m2)
        dilatedMask = dm1 + dm2
        Mask = m1 + m2
        extramask = dilatedMask ^ Mask
        bone_thresh = 210
        pad_value = 170

        im[np.isnan(im)] =- 2000
        sliceim = lumTrans(im)
        sliceim = sliceim * dilatedMask + pad_value * (1 - dilatedMask).astype('uint8')
        bones = sliceim * extramask > bone_thresh
        sliceim[bones] = pad_value
        sliceim1 = resample(sliceim, spacing, resolution, order=1)[0]
        sliceim2 = sliceim1[
            extendbox[0, 0]:extendbox[0, 1],
            extendbox[1, 0]:extendbox[1, 1],
            extendbox[2, 0]:extendbox[2, 1]]

        sliceim = sliceim2[np.newaxis, ...]
        np.save(p.join(prep_folder, dirname + '_clean'), sliceim)
        np.save(p.join(prep_folder, dirname + '_label'), np.array([[0,0,0,0]]))
        print(dirname + ' done')
        processed = 1

    return processed


def full_prep(data_path, prep_folder, use_existing=True, **kwargs):
    n_worker = kwargs.get('n_worker')
    warnings.filterwarnings('ignore')

    if not p.exists(prep_folder):
        os.mkdir(prep_folder)

    pool = Pool(n_worker)
    dirlist = kwargs.get('dirlist') or os.listdir(data_path)
    print('start preprocessing %i directories...' % len(dirlist))

    partial_savenpy = partial(
        savenpy, prep_folder=prep_folder, data_path=data_path,
        use_existing=use_existing)

    mapped = pool.map(partial_savenpy, dirlist)
    pool.close()
    pool.join()
    print('end preprocessing')
    return mapped
