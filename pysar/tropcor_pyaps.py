#! /usr/bin/env python
############################################################
# Program is part of PySAR v1.0                            #
# Copyright(c) 2015, Heresh Fattahi                        #
# Author:  Heresh Fattahi                                  #
############################################################
# Yunjun, Feb 2017: add closest_weather_product_time()
#                   add get_delay()
#                   use argparse instead of getopt


import os
import sys
import argparse
import re

try:
    import pyaps as pa
except:
    sys.exit('Cannot import pyaps into Python!')

import h5py
import numpy as np

import pysar._datetime as ptime
import pysar._pysar_utilities as ut
import pysar._readfile as readfile
import pysar._writefile as writefile


###############################################################
def closest_weather_product_time(sar_acquisition_time, grib_source='ECMWF'):
    '''Find closest available time of weather product from SAR acquisition time
    Inputs:
        sar_acquisition_time - string, SAR data acquisition time in seconds
        grib_source - string, Grib Source of weather reanalysis product
    Output:
        grib_hr - string, time of closest available weather product 
    '''
    # Get hour/min of SAR acquisition time
    sar_time = float(sar_acquisition_time)
    sar_hh = int(sar_time/3600.0)
    sar_mm = int((sar_time-3600.0*sar_hh) / 60.0)
    
    # Find closest time in available weather products
    grib_hr_list = [0, 6, 12, 18]
    grib_hr = min(grib_hr_list, key=lambda x:abs(x-sar_hh))
    
    # Adjust time output format
    if grib_source == 'NARR':
        grib_hr = "%02d"%grib_hr
    else:
        grib_hr = "%02d:00"%grib_hr
    return grib_hr


def get_delay(grib_file, atr, inps_dict):
    # Get delay matrix using PyAPS
    if 'X_FIRST' in atr.keys():
        aps = pa.PyAPS_geo(grib_file, inps_dict['dem_file'], grib=inps_dict['grib_source'],\
                           verb=True, Del=inps_dict['delay_type'])
    else:
        aps = pa.PyAPS_rdr(grib_file, inps_dict['dem_file'], grib=inps_dict['grib_source'],\
                           verb=True, Del=inps_dict['delay_type'])
    phs = np.zeros((aps.ny, aps.nx))
    aps.getdelay(phs, inc=0.0)
    
    # Get relative phase delay in space
    yref = int(atr['ref_y'])
    xref = int(atr['ref_x'])
    phs -= phs[yref, xref]
    
    # project into LOS direction
    phs /= np.cos(inps_dict['incidence_angle'])
    
    # reverse the sign for consistency between different phase correction steps/methods
    phs *= -1
    
    return phs


###############################################################
EXAMPLE='''example:
  tropcor_pyaps.py timeseries.h5 -d radar_8rlks.hgt
  tropcor_pyaps.py timeseries.h5 -d radar_8rlks.hgt -s NARR
  tropcor_pyaps.py timeseries.h5 -d radar_8rlks.hgt -s MERRA --delay dry -i 23
  tropcor_pyaps.py timeseries_LODcor.h5 -d radar_8rlks.hgt -s ECMWF 

  tropcor_pyaps.py -s ECMWF --hour 18:00 --date-list date_list.txt --download
  tropcor_pyaps.py -s ECMWF --hour 18:00 --date-list bl_list.txt   --download
'''

REFERENCE='''reference:
  Jolivet, R., R. Grandin, C. Lasserre, M.-P. Doin and G. Peltzer (2011), Systematic InSAR tropospheric
  phase delay corrections from global meteorological reanalysis data, Geophys. Res. Lett., 38, L17311,
  doi:10.1029/2011GL048757
'''

TEMPLATE='''
pysar.troposphericDelay.method        = pyaps   #[pyaps, height-correlation] 
pysar.troposphericDelay.weatherModel  = ECMWF   #[ECMWF, ERA, MERRA, NARR]
'''


def cmdLineParse():
    parser = argparse.ArgumentParser(description='Tropospheric correction using weather models\n'+\
                                     '  PyAPS is used to download and calculate the delay for each time-series epoch.',\
                                     formatter_class=argparse.RawTextHelpFormatter,\
                                     epilog=REFERENCE+'\n'+EXAMPLE)

    parser.add_argument(dest='timeseries_file', nargs='?', help='timeseries HDF5 file, i.e. timeseries.h5')
    parser.add_argument('-d','--dem', dest='dem_file',\
                        help='DEM file, i.e. radar_4rlks.hgt, srtm1.dem')
    parser.add_argument('--weather-dir', dest='weather_dir', \
                        help='directory to put downloaded weather data, i.e. ./../WEATHER\n'+\
                             'use directory of input timeseries_file if not specified.')
    parser.add_argument('--delay', dest='delay_type', default='comb', choices={'comb','dry','wet'},\
                        help='Delay type to calculate, comb contains both wet and dry delays')
    parser.add_argument('--download', action='store_true', help='Download weather data only.')
    parser.add_argument('--date-list', dest='date_list_file',\
                        help='Read the first column of text file as list of date to download data\n'+\
                             'in YYYYMMDD or YYMMDD format')

    parser.add_argument('-s', dest='weather_model',\
                        default='ECMWF', choices={'ECMWF','ERA-Interim','ERA','MERRA','MERRA2','NARR'},\
                        help='source of the atmospheric data')
    parser.add_argument('-i', dest='incidence_angle',\
                        help='a file containing all incidence angles, or\n'+\
                             'one average value presenting the whole area, if not input, average look angle will be used.')
    parser.add_argument('--hour', help='time of data (ECMWF takes hh:mm, NARR takes hh only)')

    parser.add_argument('--template', dest='template_file',\
                        help='template file with input options below:\n'+TEMPLATE)
    parser.add_argument('-o', dest='out_file', help='Output file name for trospheric corrected timeseries.')

    inps = parser.parse_args()

    # Correcting TIMESERIES or DOWNLOAD DATA ONLY, required one of them
    if not inps.timeseries_file and not inps.download:
        parser.print_help()
        sys.exit(1)
    return inps


###############################################################
def main(argv):
    inps = cmdLineParse()

    if inps.timeseries_file:
        inps.timeseries_file = ut.get_file_list([inps.timeseries_file])[0]
        atr = readfile.read_attribute(inps.timeseries_file)

    if inps.dem_file:
        inps.dem_file = ut.get_file_list([inps.dem_file])[0]
        # Convert DEM to ROIPAC format
        if os.path.splitext(inps.dem_file)[1] in ['.h5']:
            print 'convert DEM file to ROIPAC format'
            dem, atr_dem = readfile.read(inps.dem_file)
            if 'Y_FIRST' in atr_dem.keys():
                atr_dem['FILE_TYPE'] = '.dem'
            else:
                atr_dem['FILE_TYPE'] = '.hgt'
            outname = os.path.splitext(inps.dem_file)[0]+'4pyaps'+atr_dem['FILE_TYPE']
            inps.dem_file = writefile.write(dem, atr_dem, outname)

    print '*******************************************************************************'
    print 'Downloading weather model data ...'
    
    ## Get Grib Source
    if inps.weather_model in ['ECMWF','ERA-Interim']:   inps.grib_source = 'ECMWF'
    elif inps.weather_model == 'ERA'  :                 inps.grib_source = 'ERA'
    elif inps.weather_model == 'MERRA':                 inps.grib_source = 'MERRA'
    elif inps.weather_model == 'NARR' :                 inps.grib_source = 'NARR'
    else: raise Reception('Unrecognized weather model: '+inps.weather_model)
    print 'grib source: '+inps.grib_source

    ## Grib data directory
    if not inps.weather_dir:
        if inps.timeseries_file:
            inps.weather_dir = os.path.dirname(os.path.abspath(inps.timeseries_file))+'/../WEATHER'
        elif inps.dem_file:
            inps.weather_dir = os.path.dirname(os.path.abspath(inps.dem_file))+'/../WEATHER'
        else:
            inps.weather_dir = os.path.abspath(os.getcwd())
    print 'Store weather data into directory: '+inps.weather_dir
    grib_dir = inps.weather_dir+'/'+inps.grib_source
    if not os.path.isdir(grib_dir):
        print 'making directory: '+grib_dir
        os.makedirs(grib_dir)

    ## Get Acquisition time
    if not inps.hour:
        inps.hour = closest_weather_product_time(atr['CENTER_LINE_UTC'], inps.grib_source)
    print 'Time of cloest available product: '+inps.hour
    
    ## Get grib file list and date list
    inps.grib_file_list = []
    if not inps.date_list_file:
        h5timeseries = h5py.File(inps.timeseries_file, 'r')
        dateList = sorted(h5timeseries['timeseries'].keys())
        h5timeseries.close()
        print 'read date list info from: '+inps.timeseries_file
    else:
        dateList = ptime.yyyymmdd(np.loadtxt(inps.date_list_file, dtype=str, usecols=(0,)).tolist())
        print 'read date list info from: '+inps.date_list_file

    for d in dateList:
        if   inps.grib_source == 'ECMWF':  grib_file = grib_dir+'/ERA-Int_'+d+'_'+inps.hour+'.grb'
        elif inps.grib_source == 'ERA'  :  grib_file = grib_dir+'/ERA_'+d+'_'+inps.hour+'.grb'
        elif inps.grib_source == 'MERRA':  grib_file = grib_dir+'/merra-'+d+'-'+inps.hour+'.hdf'
        elif inps.grib_source == 'NARR' :  grib_file = grib_dir+'/narr-a_221_'+d+'_'+inps.hour+'00_000.grb'
        inps.grib_file_list.append(grib_file)

    ## Get date list to download
    grib_file_existed = ut.get_file_list(inps.grib_file_list)
    if grib_file_existed:
        grib_filesize_mode = ut.mode([os.path.getsize(i) for i in grib_file_existed])
        grib_file_corrupted = [i for i in grib_file_existed if os.path.getsize(i) != grib_filesize_mode]
        print 'number of grib files existed    : %d' % len(grib_file_existed)
        print 'file size mode: %d' % grib_filesize_mode
        if grib_file_corrupted:
            print '------------------------------------------------------------------------------'
            print 'corrupted grib files detected! Delete them and re-download...'
            print 'number of grib files corrupted  : %d' % len(grib_file_corrupted)
            for i in grib_file_corrupted:
                rmCmd = 'rm '+i
                print rmCmd
                os.system(rmCmd)
                grib_file_existed.remove(i)
            print '------------------------------------------------------------------------------'
    grib_file2download = sorted(list(set(inps.grib_file_list) - set(grib_file_existed)))
    date_list2download = [str(re.findall('\d{8}', i)[0]) for i in grib_file2download]
    print 'number of grib files to download: %d' % len(date_list2download)
    print '------------------------------------------------------------------------------\n'

    ## Download grib file using PyAPS
    if   inps.grib_source == 'ECMWF':  pa.ECMWFdload(date_list2download, inps.hour, grib_dir)
    elif inps.grib_source == 'ERA'  :  pa.ERAdload(  date_list2download, inps.hour, grib_dir)
    elif inps.grib_source == 'MERRA':  pa.MERRAdload(date_list2download, inps.hour, grib_dir)
    elif inps.grib_source == 'NARR' :  pa.NARRdload( date_list2download, inps.hour, grib_dir)

    if inps.download:
        print 'Download completed, exit as planned.'
        return

    print '*******************************************************************************'
    print 'Calcualting delay for each epoch.'

    ## Get Incidence angle: to map the zenith delay to the slant delay
    if inps.incidence_angle:
        if os.path.isfile(inps.incidence_angle):
            inps.incidence_angle = readfile.read(inps.incidence_angle)[0]
        else:
            inps.incidence_angle = float(inps.incidence_angle)
            print 'incidence angle: '+str(inps.incidence_angle)
    else:
        print 'calculating incidence angle ...'
        inps.incidence_angle = ut.incidence_angle(atr)
    inps.incidence_angle = inps.incidence_angle*np.pi/180.0
    
    ## Create delay hdf5 file
    tropFile = inps.grib_source+'.h5'
    print 'writing >>> '+tropFile
    h5trop = h5py.File(tropFile, 'w')
    group_trop = h5trop.create_group('timeseries')
    
    ## Create tropospheric corrected timeseries hdf5 file
    if not inps.out_file:
        ext = os.path.splitext(inps.timeseries_file)[1]
        inps.out_file = os.path.splitext(inps.timeseries_file)[0]+'_'+inps.grib_source+'.h5'
    print 'writing >>> '+inps.out_file
    h5timeseries_tropCor = h5py.File(inps.out_file, 'w')
    group_tropCor = h5timeseries_tropCor.create_group('timeseries')

    ## Calculate phase delay on reference date
    if 'ref_date' in atr.keys():
        ref_idx = dateList.index(atr['ref_date'])
    else:
        ref_idx = 0
    print 'calculating phase delay on reference date: '+dateList[ref_idx]
    phs_ref = get_delay(inps.grib_file_list[ref_idx], atr, vars(inps))

    ## Loop to calculate phase delay on the other dates
    h5timeseries = h5py.File(inps.timeseries_file, 'r')
    for i in range(len(inps.grib_file_list)):
        # Get phase delay
        grib_file = inps.grib_file_list[i] 
        if not i == ref_idx:
            print dateList[i]
            phs = get_delay(grib_file, atr, vars(inps))
        else:
            phs = np.copy(phs_ref)
        # Get relative phase delay in time
        phs -= phs_ref
        
        # Write dataset
        print 'writing hdf5 file ...'
        data = h5timeseries['timeseries'].get(dateList[i])[:]
        dset  = group_tropCor.create_dataset(dateList[i], data=data-phs, compression='gzip')
        dset  = group_trop.create_dataset(dateList[i], data=phs, compression='gzip')
    
    ## Write Attributes
    for key,value in atr.iteritems():
        group_tropCor.attrs[key] = value
        group_trop.attrs[key] = value
    
    h5timeseries.close()
    h5timeseries_tropCor.close()
    h5trop.close()

    # Delete temporary DEM file in ROI_PAC format
    if '4pyaps' in inps.dem_file:
        rmCmd = 'rm '+inps.dem_file+' '+inps.dem_file+'.rsc '
        print rmCmd
        os.system(rmCmd)
    
    print 'Done.'

    return


###############################################################
if __name__ == '__main__':
    main(sys.argv[1:])

