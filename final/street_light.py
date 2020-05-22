import sys
import signal
import os
import ctypes
import pickle
import datetime

from multiprocessing import Pool, TimeoutError
import multiprocessing as mp

import math
import numpy as np
import pandas as pd
from tqdm.autonotebook import tqdm


def calc_distance(origin, destination):
    lat1, lon1 = origin
    lat2, lon2 = destination
    radius = 6371  # km

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) * math.sin(dlat / 2) + math.cos(math.radians(lat1)) \
        * math.cos(math.radians(lat2)) * math.sin(dlon / 2) * math.sin(dlon / 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    d = radius * c

    return d


def calc_process(proc_num, df, df_light, queue, stopped, tqdm_lock):
    tqdm.set_lock(tqdm_lock)

    for index, row in tqdm(df.iterrows(), total=df.shape[0], desc='Process {} : all projects'.format(proc_num + 1),
                           position=proc_num):
        if stopped.value is True:
            break

        case_id = row['ID']

        light_count_dict = {
            'have_light': False,
            'count_50meter': 0,
            'count_100meter': 0,
            'count_200meter': 0,
            'count_500meter': 0,
            'count_1000meter': 0,
            'nearest': np.nan
        }

        lat, lng = row['Latitude'], row['Longitude']
        if np.isnan(lat) or np.isnan(lng):
            pass
        else:
            district = row['District_STR']
            date = datetime.datetime.strptime(row['Date'], '%m/%d/%Y %I:%M:%S %p')
            df_temp = df_light.loc[district]
            lights = df_temp[(df_temp['Creation Date'] < date) &
                             (df_temp['Completion Date'] > date)]

            if len(lights) > 0:
                for _, light_row in lights.iterrows():
                    lat2, lng2 = light_row['Latitude'], light_row['Longitude']
                    if np.isnan(lat2) or np.isnan(lng2):
                        continue

                    distance = calc_distance((lat, lng), (lat2, lng2))

                    if np.isnan(light_count_dict['nearest']) or light_count_dict['nearest'] > distance:
                        light_count_dict['nearest'] = distance

                    if distance <= 0.05:
                        light_count_dict['count_50meter'] += 1

                    if distance <= 0.1:
                        light_count_dict['count_100meter'] += 1
                        light_count_dict['have_light'] = True

                    if distance <= 0.2:
                        light_count_dict['count_200meter'] += 1
                        light_count_dict['have_light'] = True

                    if distance <= 0.5:
                        light_count_dict['count_500meter'] += 1

                    if distance <= 1:
                        light_count_dict['count_1000meter'] += 1

        queue.put((case_id, light_count_dict))


def save_data_process(queue, pickle_path):
    if os.path.isfile(pickle_path):
        with open(pickle_path, 'rb') as pickle_file:
            cache_dict = pickle.load(pickle_file)
    else:
        cache_dict = {}

    while True:
        record = queue.get()
        if record is None:
            break

        case_id, data = record
        cache_dict[case_id] = data

    with open(pickle_path, 'wb') as pickle_file:
        pickle_file.write(pickle.dumps(cache_dict))



def main():
    stopped = mp.Value(ctypes.c_bool, False)

    queue = mp.Queue(-1)

    def on_stop(signal, frame):
        nonlocal stopped
        stopped.value = True

    signal.signal(signal.SIGINT, on_stop)
    signal.signal(signal.SIGTERM, on_stop)

    # load data
    print('loading data...')
    df = pd.read_csv('csv/Crimes_-_2010_to_present.csv')
    df = df[df['Year'] >= 2017].reset_index()
    df['District_STR'] = df['District'].fillna(0).astype(int).astype(str)

    # filter out downloaded data
    pickle_path = 'pickle/street_light_out_count.pickle'

    if os.path.isfile(pickle_path):
        with open(pickle_path, 'rb') as pickle_file:
            cache_dict = pickle.load(pickle_file)
    else:
        cache_dict = {}

    index_filter = [True] * df.shape[0]
    df = df.set_index(['ID'])

    for case_id, data in cache_dict.items():
        try:
            index = df.index.get_loc(case_id)
            index_filter[index] = False
        except KeyError:
            continue

    del cache_dict

    df = df[index_filter].reset_index()
    if df.shape[0] == 0:
        return

    # load street light data
    df_light = pd.read_csv('csv/311_Service_Requests_-_Street_Lights_-_One_Out_-_Historical.csv')
    # convert datetime string to datetime object
    df_light['Creation Date'] = pd.to_datetime(df_light['Creation Date'])
    df_light['Completion Date'] = pd.to_datetime(df_light['Completion Date'])
    # set index to 'Police District' for lookup
    df_light['Police District'] = df_light['Police District'].fillna(0).astype(int).astype(str)
    df_light.set_index('Police District', inplace=True)

    print('start process...')

    save_process = mp.Process(target=save_data_process,
                              args=(queue, pickle_path))
    save_process.start()

    # proc_num = mp.cpu_count()
    proc_num = 8
    length = df.shape[0]
    step = math.ceil(length / proc_num)
    process_list = []
    for i, index_start in enumerate(range(0, length, step)):
        index_end = index_start + step
        batch_df = df.iloc[index_start: index_end]

        process = mp.Process(target=calc_process,
                             args=(i, batch_df, df_light, queue, stopped, tqdm.get_lock()))
        process.start()
        process_list.append(process)

    for process in process_list:
        process.join()
    queue.put(None)
    save_process.join()


if __name__ == "__main__":
    main()
