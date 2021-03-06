#! /usr/bin/env python
############################################################
# Program is part of PySAR v1.0                            #
# Copyright(c) 2013, Heresh Fattahi                        #
# Author:  Heresh Fattahi                                  #
############################################################
# Yunjun, Dec 2015: Add find_lat_lon(), add 'ref_lat','ref_lon' for geocoded file
# Yunjun, Jan 2016: Add input option for template file
# Yunjun, Apr 2016: Add maskFile input option
# Yunjun, Jun 2016: Add seed_attributes(), support to all file types
#                   Add reference file option


import os
import sys
import argparse

import h5py
import matplotlib.pyplot as plt
import numpy as np
import random

import pysar._datetime as ptime
import pysar._readfile as readfile
import pysar._writefile as writefile
import pysar._pysar_utilities as ut
import pysar.subset as subset
from pysar._readfile import multi_group_hdf5_file, multi_dataset_hdf5_file, single_dataset_hdf5_file


########################################## Sub Functions #############################################
###############################################################
###############################################################
def nearest(x, tbase,xstep):
    ## """ find nearest neighbour """
    dist = np.sqrt((tbase -x)**2)
    if min(dist) <= np.abs(xstep):
        indx=dist==min(dist)
    else:
        indx=[]
    return indx


###############################################################
def seed_file_reference_value(File, outName, refList, ref_y='', ref_x=''):
    ## Seed Input File with reference value in refList
    print 'Reference value: '
    print refList

    #####  IO Info
    atr = readfile.read_attribute(File)
    k = atr['FILE_TYPE']
    print 'file type: '+k

    ##### Multiple Dataset File
    if k in ['timeseries','interferograms','wrapped','coherence']:
        ##### Input File Info
        h5file = h5py.File(File,'r')
        epochList = sorted(h5file[k].keys())
        epochNum  = len(epochList)

        ##### Check Epoch Number
        if not epochNum == len(refList):
            print '\nERROR: Reference value has different epoch number'+\
                  'from input file.'
            print 'Reference List epoch number: '+str(refList)
            print 'Input file     epoch number: '+str(epochNum)
            sys.exit(1)
  
        ##### Output File Info
        h5out = h5py.File(outName,'w')
        group = h5out.create_group(k)
        print 'writing >>> '+outName
        prog_bar = ptime.progress_bar(maxValue=epochNum, prefix='seeding: ')

    ## Loop
    if k == 'timeseries':
        print 'number of acquisitions: '+str(epochNum)
        for i in range(epochNum):
            epoch = epochList[i]
            data = h5file[k].get(epoch)[:]
            data -= refList[i]
            dset = group.create_dataset(epoch, data=data, compression='gzip')
            prog_bar.update(i+1, suffix=epoch)
        atr  = seed_attributes(atr,ref_x,ref_y)
        for key,value in atr.iteritems():
            group.attrs[key] = value

    elif k in ['interferograms','wrapped','coherence']:
        print 'number of interferograms: '+str(epochNum)
        date12_list = ptime.list_ifgram2date12(epochList)
        for i in range(epochNum):
            epoch = epochList[i]
            #print epoch
            data = h5file[k][epoch].get(epoch)[:]
            atr  = h5file[k][epoch].attrs

            data -= refList[i]
            atr  = seed_attributes(atr,ref_x,ref_y)

            gg = group.create_group(epoch)
            dset = gg.create_dataset(epoch, data=data, compression='gzip')
            for key, value in atr.iteritems():
                gg.attrs[key] = value

            prog_bar.update(i+1, suffix=date12_list[i])
  
    ##### Single Dataset File
    else:
        print 'writing >>> '+outName
        data,atr = readfile.read(File)
        data -= refList
        atr  = seed_attributes(atr,ref_x,ref_y)
        writefile.write(data,atr,outName)
  
    ##### End & Cleaning
    try:
        prog_bar.close()
        h5file.close()
        h5out.close()
    except:
        pass

    return outName


def seed_file_inps(File, inps=None, outFile=None):
    '''Seed input file with option from input namespace
    Return output file name if succeed; otherwise, return None
    '''
    # Optional inputs
    if not outFile:  outFile = 'Seeded_'+os.path.basename(File)
    if not inps:  inps = cmdLineParse([''])
    print '----------------------------------------------------'
    print 'seeding file: '+File
    
    # Get stack and mask
    stack = ut.get_file_stack(File, inps.mask_file)
    mask = ~np.isnan(stack)
    if np.nansum(mask) == 0.0:
        print '\n*****************************************************'
        print   'ERROR:'
        print   'There is no pixel that has valid phase value in all datasets.' 
        print   'Check the file!'
        print   'Seeding failed'
        sys.exit(1)
    
    # 1. Reference using global average 
    if inps.method == 'global-average':
        print '\n---------------------------------------------------------'
        print 'Automatically Seeding using Global Spatial Average Value '
        print '---------------------------------------------------------'
        print 'Calculating the global spatial average value for each epoch'+\
              ' of all valid pixels ...'
        atr = readfile.read_attribute(File)
        width = int(atr['WIDTH'])
        length = int(atr['FILE_LENGTH'])
        box = (0,0,width,length)
        meanList = ut.spatial_average(File, mask, box)
        inps.ref_y = ''
        inps.ref_x = ''
        outFile = seed_file_reference_value(File, outFile, meanList, inps.ref_y, inps.ref_x)
        return outFile

    # 2. Reference using specific pixel
    # 2.1 Find reference y/x
    if not inps.ref_y or not inps.ref_x:
        if inps.coherence_file:
            inps.method = 'max-coherence'
            inps.ref_y, inps.ref_x = select_max_coherence_yx(inps.coherence_file, mask, inps.min_coherence)
        elif inps.method == 'random':
            inps.ref_y, inps.ref_x = random_select_reference_yx(mask)
        elif inps.method == 'manual':
            inps = manual_select_reference_yx(stack, inps)

    # 2.2 Seeding file with reference y/x
    if inps.ref_y and inps.ref_x and mask[inps.ref_y, inps.ref_x]:
        if inps.mark_attribute:
            print 'Add/update ref_x/y attribute to file: '+File
            atr_ref = dict()
            atr_ref['ref_x'] = inps.ref_x
            atr_ref['ref_y'] = inps.ref_y
            print atr_ref
            outFile = ut.add_attribute(File, atr_ref)
        else:
            print 'Referencing input file to pixel in y/x: (%d, %d)'%(inps.ref_y, inps.ref_x)
            box = (inps.ref_x, inps.ref_y, inps.ref_x+1, inps.ref_y+1)
            refList = ut.spatial_average(File, mask, box)
            outFile = seed_file_reference_value(File, outFile, refList, inps.ref_y, inps.ref_x)
    else:
        raise ValueError('Can not find reference y/x or Nan value.')
    
    return outFile


###############################################################
def seed_attributes(atr_in,x,y):
    atr = dict()
    for key, value in atr_in.iteritems():
        atr[key] = str(value)
    
    atr['ref_y']=y
    atr['ref_x']=x
    if 'X_FIRST' in atr.keys():
        atr['ref_lat'] = subset.coord_radar2geo(y,atr,'y')
        atr['ref_lon'] = subset.coord_radar2geo(x,atr,'x')

    return atr


###############################################################
def manual_select_reference_yx(stack, inps):
    '''
    Input: 
        data4display : 2D np.array, stack of input file
        inps    : namespace, with key 'ref_x' and 'ref_y', which will be updated
    '''
    print '\n---------------------------------------------------------'
    print   'Manual select reference point ...'
    print   'Click on a pixel that you want to choose as the refernce '
    print   '    pixel in the time-series analysis;'
    print   'Then close the displayed window to continue.'
    print   '---------------------------------------------------------'

    ## Mutable object
    ## ref_url: http://stackoverflow.com/questions/15032638/how-to-return
    #           -a-value-from-button-press-event-matplotlib
    SeedingDone = {}
    SeedingDone['key'] = 'no'

    ##### Display
    fig = plt.figure()
    ax  = fig.add_subplot(111)
    ax.imshow(stack)

    ##### Selecting Point
    def onclick(event):
        if event.button==1:
            print 'click'
            x = int(event.xdata+0.5)
            y = int(event.ydata+0.5)

            if not np.isnan(stack[y][x]):
                print 'valid input reference y/x: '+str([y, x])
                inps.ref_y = y
                inps.ref_x = x
                #plt.close(fig) 
            else:
                print '\nWARNING:'
                print 'The selectd pixel has NaN value in data.'
                print 'Try a difference location please.'
    cid = fig.canvas.mpl_connect('button_press_event', onclick)
    plt.show()

    return inps


def select_max_coherence_yx(cohFile, mask=None, min_coh=0.85):
    '''Select pixel with coherence > min_coh in random'''
    print '\n---------------------------------------------------------'
    print   'select pixel with coherence > '+str(min_coh)+' in random'
    print 'use coherence file: '+cohFile
    coh, coh_atr = readfile.read(cohFile)
    if not mask is None:
        coh[mask==0] = 0.0
    coh_mask = coh >= min_coh
    y, x = random_select_reference_yx(coh_mask, print_message=False)
    #y, x = np.unravel_index(np.argmax(coh), coh.shape)
    print   'y/x: '+str([y, x])
    print   '---------------------------------------------------------'

    return y, x


def random_select_reference_yx(data_mat, print_message=True):
    if print_message:
        print '\n---------------------------------------------------------'
        print   'Random select reference point ...'
        print   '---------------------------------------------------------'

    nrow,ncol = np.shape(data_mat)
    y = random.choice(range(nrow))
    x = random.choice(range(ncol))
    while data_mat[y,x] == 0:
        y = random.choice(range(nrow))
        x = random.choice(range(ncol))
    return y,x


###############################################################
def print_warning(next_method):
    print '-----------------------------------------------------'
    print 'WARNING:'
    print 'Input file is not referenced to the same pixel yet!'
    print '-----------------------------------------------------'
    print 'Continue with default automatic seeding method: '+next_method+'\n'
    return


###############################################################
def read_seed_template2inps(template_file, inps=None):
    '''Read seed/reference info from template file and update input namespace'''
    if not inps:
        inps = cmdLineParse([''])
    
    template = readfile.read_template(template_file)
    key_list = template.keys()

    prefix = 'pysar.reference.'

    key = prefix+'yx'
    if key in key_list:
        value = template[key]
        if value not in ['auto','no']:
            inps.ref_y, inps.ref_x = [int(i) for i in value.split(',')]

    key = prefix+'lalo'
    if key in key_list:
        value = template[key]
        if value not in ['auto','no']:
            inps.ref_lat, inps.ref_lon = [float(i) for i in value.split(',')]

    key = prefix+'maskFile'
    if key in key_list:
        value = template[key]
        if value == 'auto':
            inps.mask_file = None
        elif value == 'no':
            inps.mask_file = None
        else:
            inps.mask_file = value

    key = prefix+'coherenceFile'
    if key in key_list:
        value = template[key]
        if value == 'auto':
            inps.coherence_file = 'averageSpatialCoherence.h5'
        else:
            inps.coherence_file = value

    key = prefix+'minCoherence'
    if key in key_list:
        value = template[key]
        if value == 'auto':
            inps.min_coherence = 0.85
        else:
            inps.min_coherence = float(value)

    return inps


def read_seed_reference2inps(reference_file, inps=None):
    '''Read seed/reference info from reference file and update input namespace'''
    if not inps:
        inps = cmdLineParse([''])
    atr_ref = readfile.read_attribute(inps.reference_file)
    atr_ref_key_list = atr_ref.keys()
    if (not inps.ref_y or not inps.ref_x) and 'ref_x' in atr_ref_key_list:
        inps.ref_y = int(atr_ref['ref_y'])
        inps.ref_x = int(atr_ref['ref_x'])
    if (not inps.ref_lat or not inps.ref_lon) and 'ref_lon' in atr_ref_key_list:
        inps.ref_lat = float(atr_ref['ref_lat'])
        inps.ref_lon = float(atr_ref['ref_lon'])
    return inps


#########################################  Usage  ##############################################
TEMPLATE='''
## reference all interferograms to one common point in space
## auto - randomly select a pixel with coherence > minCoherence
pysar.reference.yx            = auto   #[257,151 / auto]
pysar.reference.lalo          = auto   #[31.8,130.8 / auto]

pysar.reference.coherenceFile = auto   #[file name], auto for averageSpatialCoherence.h5
pysar.reference.minCoherence  = auto   #[0.0-1.0], auto for 0.85, minimum coherence for auto method
pysar.reference.maskFile      = auto   #[file name / no], auto for mask.h5
'''

NOTE='''note: Reference value cannot be nan, thus, all selected reference point must be:
  a. non zero in mask, if mask is given
  b. non nan  in data (stack)
'''

EXAMPLE='''example:
  seed_data.py unwrapIfgram.h5 -t pysarApp_template.txt  --mark-attribute --trans geomap_4rlks.trans

  seed_data.py timeseries.h5     -r Seeded_velocity.h5
  seed_data.py 091120_100407.unw -y 257    -x 151      -m Mask.h5
  seed_data.py geo_velocity.h5   -l 34.45  -L -116.23  -m Mask.h5
  seed_data.py unwrapIfgram.h5   -l 34.45  -L -116.23  --trans geomap_4rlks.trans
  
  seed_data.py unwrapIfgram.h5 -c average_spatial_coherence.h5
  seed_data.py unwrapIfgram.h5 --method manual
  seed_data.py unwrapIfgram.h5 --method random
  seed_data.py timeseries.h5   --method global-average 
'''

def cmdLineParse():
    parser = argparse.ArgumentParser(description='Reference to the same pixel in space.',\
                                     formatter_class=argparse.RawTextHelpFormatter,\
                                     epilog=NOTE+'\n'+EXAMPLE)
    
    parser.add_argument('file', nargs='+', help='file(s) to be referenced.')
    parser.add_argument('-m','--mask', dest='mask_file', help='mask file')
    parser.add_argument('-o', '--outfile', help='output file name, disabled when more than 1 input files.')
    parser.add_argument('--no-parallel', dest='parallel', action='store_false',\
                        help='Disable parallel processing. Diabled auto for 1 input file.\n')
    parser.add_argument('--mark-attribute', dest='mark_attribute', action='store_true',\
                        help='mark/update reference attributes in input file only\n'+\
                             'do not update data matrix value nor write new file')

    coord_group = parser.add_argument_group('input coordinates')
    coord_group.add_argument('-y','--row', dest='ref_y', type=int, help='row/azimuth  number of reference pixel')
    coord_group.add_argument('-x','--col', dest='ref_x', type=int, help='column/range number of reference pixel')
    coord_group.add_argument('-l','--lat', dest='ref_lat', type=float, help='latitude  of reference pixel')
    coord_group.add_argument('-L','--lon', dest='ref_lon', type=float, help='longitude of reference pixel')
    
    coord_group.add_argument('-r','--reference', dest='reference_file', help='use reference/seed info of this file')
    coord_group.add_argument('--trans', dest='trans_file',\
                             help='Mapping transformation file from SAR to DEM, i.e. geomap_4rlks.trans\n'+\
                                  'Needed for radar coord input file with --lat/lon seeding option.')
    coord_group.add_argument('-t','--template', dest='template_file',\
                             help='template with reference info as below:\n'+TEMPLATE)

    parser.add_argument('-c','--coherence', dest='coherence_file',\
                        help='use input coherence file to find the pixel with max coherence for reference pixel.')
    parser.add_argument('--min-coherence', dest='min_coherence', type=float, default=0.85,\
                        help='minimum coherence of reference pixel for max-coherence method.')
    parser.add_argument('--method', default='random',\
                        choices=['input-coord','max-coherence','manual','random','global-average'], \
                        help='method to select reference pixel:\n\n'+\
                             'input-coord   : input specific coordinates, enabled when there are coordinates input\n'+\
                             'max-coherence : select pixel with highest coherence value as reference point\n'+\
                             '                enabled when there is --coherence option input\n'+\
                             'manual        : display stack of input file and manually select reference point\n'+\
                             'random        : random select pixel as reference point\n'+\
                             'global-average: for each dataset, use its spatial average value as reference value\n'+\
                             '                reference pixel is changing for different datasets\n')
    
    inps = parser.parse_args()
    return inps


#######################################  Main Function  ########################################
def main(argv):
    inps = cmdLineParse()
    inps.file = ut.get_file_list(inps.file)
    
    atr = readfile.read_attribute(inps.file[0])
    length = int(atr['FILE_LENGTH'])
    width  = int(atr['WIDTH'])

    ##### Check Input Coordinates
    # Read ref_y/x/lat/lon from reference/template
    # priority: Direct Input > Reference File > Template File
    if inps.template_file:
        print 'reading reference info from template: '+inps.template_file
        inps = read_seed_template2inps(inps.template_file, inps)
    if inps.reference_file:
        print 'reading reference info from reference: '+inps.reference_file
        inps = read_seed_reference2inps(inps.reference_file, inps)
    
    ## Do not use ref_lat/lon input for file in radar-coord
    #if not 'X_FIRST' in atr.keys() and (inps.ref_lat or inps.ref_lon):
    #    print 'Lat/lon reference input is disabled for file in radar coord.'
    #    inps.ref_lat = None
    #    inps.ref_lon = None
    
    # Convert ref_lat/lon to ref_y/x
    if inps.ref_lat and inps.ref_lon:
        if 'X_FIRST' in atr.keys():
            inps.ref_y = subset.coord_geo2radar(inps.ref_lat, atr, 'lat')
            inps.ref_x = subset.coord_geo2radar(inps.ref_lon, atr, 'lon')
        else:
            # Convert lat/lon to az/rg for radar coord file using geomap*.trans file
            inps.ref_y, inps.ref_x = ut.glob2radar(np.array(inps.ref_lat), np.array(inps.ref_lon),\
                                                   inps.trans_file, atr)[0:2]
        print 'Input reference point in lat/lon: '+str([inps.ref_lat, inps.ref_lon])
    print 'Input reference point in   y/x  : '+str([inps.ref_y, inps.ref_x])
    
    # Do not use ref_y/x outside of data coverage
    if (inps.ref_y and inps.ref_x and
        not (0<= inps.ref_y <= length and 0<= inps.ref_x <= width)):
        inps.ref_y = None
        inps.ref_x = None
        print 'WARNING: input reference point is OUT of data coverage!'
        print 'Continue with other method to select reference point.'
        
    # Do not use ref_y/x in masked out area
    if inps.ref_y and inps.ref_x and inps.mask_file:
        print 'mask: '+inps.mask_file
        mask = readfile.read(inps.mask_file)[0]
        if mask[inps.ref_y, inps.ref_x] == 0:
            inps.ref_y = None
            inps.ref_x = None
            print 'WARNING: input reference point is in masked OUT area!'
            print 'Continue with other method to select reference point.'

    ##### Select method
    if inps.ref_y and inps.ref_x:
        inps.method = 'input-coord'
    elif inps.coherence_file:
        if os.path.isfile(inps.coherence_file):
            inps.method = 'max-coherence'
        else: 
            inps.coherence_file = None
    
    if inps.method == 'manual':
        inps.parallel = False
        print 'Parallel processing is disabled for manual seeding method.'

    ##### Seeding file by file
    # check outfile and parallel option
    if inps.parallel:
        num_cores, inps.parallel, Parallel, delayed = ut.check_parallel(len(inps.file))

    if len(inps.file) == 1:
        seed_file_inps(inps.file[0], inps, inps.outfile)
        
    elif inps.parallel:
        #num_cores = min(multiprocessing.cpu_count(), len(inps.file))
        #print 'parallel processing using %d cores ...'%(num_cores)
        Parallel(n_jobs=num_cores)(delayed(seed_file_inps)(file, inps) for file in inps.file)
    else:
        for File in inps.file:
            seed_file_inps(File, inps)

    print 'Done.'
    return


################################################################################################
if __name__ == '__main__':
    main(sys.argv[1:])


