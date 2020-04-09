import json
import requests
import pandas as pd
from tqdm.autonotebook import tqdm
import pickle
from multiprocessing import Pool, TimeoutError
import multiprocessing as mp
import ctypes

import signal
import sys
import os
import math
import time

import asyncio
import aiohttp

from subscription_key import fund_daily_subscription_keys, fund_fact_subscription_keys
from period_data_config import data_configs

def load_pickle(path):
    with open(path, 'rb') as pickle_file:
        return pickle.load(pickle_file)


class RateLimiter:
    """Rate limits an HTTP client that would make get() and post() calls.
    Calls are rate-limited by host.
    https://quentin.pradet.me/blog/how-do-you-rate-limit-calls-with-aiohttp.html
    This class is not thread-safe."""
    RATE = 5  # one request per second
    MAX_TOKENS = 15

    def __init__(self, client):
        self.client = client
        self.tokens = self.MAX_TOKENS
        self.updated_at = time.monotonic()

    async def get(self, *args, **kwargs):
        await self.wait_for_token()
        # now = time.monotonic() - START
        # print(f'{now:.0f}s: ask {args[0]}')
        return self.client.get(*args, **kwargs)

    async def wait_for_token(self):
        while self.tokens < 1:
            self.add_new_tokens()
            await asyncio.sleep(0.1)
        self.tokens -= 1

    def add_new_tokens(self):
        now = time.monotonic()
        time_since_update = now - self.updated_at
        new_tokens = time_since_update * self.RATE
        if self.tokens + new_tokens >= 1:
            self.tokens = min(self.tokens + new_tokens, self.MAX_TOKENS)
            self.updated_at = now


def cal_date_range():
    years = ['2019', '2018', '2017', '2016', '2015']
    month_days = ['01-31', '02-28', '03-31', '04-30', '05-31',
                  '06-30', '07-31', '08-31', '09-30', '10-31', '11-30', '12-31']
    date_range = ['2020-01-31', '2020-02-28', '2020-03-31']

    for year in years:
        for month_day in month_days:
            date_range.append(year + '-' + month_day)

    return date_range


def cal_month_range():
    years = ['2019', '2018', '2017', '2016', '2015']
    years = ['2019']
    months = ['01', '02', '03', '04', '05',
              '06', '07', '08', '09', '10', '11', '12']
    date_range = ['202001', '202002', '202003']

    for year in years:
        for month in months:
            date_range.append(year + str(month))

    return date_range


async def download(session, url, proj_id, date):
    async with await session.get(url.format(proj_id=proj_id, date=date)) as response:
        # print(response.status)
        if response.status == 200:
            data = await response.json()
            return (proj_id, date, data)
        elif response.status == 429:
            print(await response.text())
            return None
        elif response.status == 204:
            return (proj_id, date, None)
        else:
            print(response.status)
            return None


def save_data_process(queue, pickle_path):
    if os.path.isfile(pickle_path):
        with open(pickle_path, 'rb') as pickle_file:
            project_attr_dict = pickle.load(pickle_file)
    else:
        project_attr_dict = {}

    while True:
        record = queue.get()
        if record is None:
            break

        proj_id, date, data = record
        attr_dict = project_attr_dict.get(proj_id, {})
        attr_dict[date] = data
        project_attr_dict[proj_id] = attr_dict

    with open(pickle_path, 'wb') as pickle_file:
        pickle_file.write(pickle.dumps(project_attr_dict))


async def download_all(proc_num, df, url, subscription_key, queue, stopped):
    headers = {
        'Ocp-Apim-Subscription-Key': subscription_key,
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        session = RateLimiter(session)
        tasks = []
        for index, row in df.iterrows():
            # for index, row in batch_df.iterrows():
            if stopped.value is True:
                break
            proj_id = row['project_id']
            date = row['date']
            task = asyncio.ensure_future(
                download(session, url, proj_id, date))
            tasks.append(task)
        if stopped.value is not True:
            for f in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc='Process {} : all projects'.format(proc_num+1), position=proc_num):
                if stopped.value is True:
                    break
                data = await f
                if data is None:
                    continue
                queue.put(data)


def download_all_process(proc_num, df, url, subscription_key, queue, stopped, tqdm_lock):
    tqdm.set_lock(tqdm_lock)
    # print(asyncio.get_event_loop())
    # return
    asyncio.get_event_loop().run_until_complete(
        download_all(proc_num, df, url, subscription_key, queue, stopped))


def setup_download_process(proj_ids, date_range, pickle_path, url, subscription_keys, stopped):
    proj_ids_df = pd.DataFrame(
        {'key': ['1'] * len(proj_ids), 'project_id': proj_ids})
    date_range_df = pd.DataFrame(
        {'key': ['1'] * len(date_range), 'date': date_range})

    project_id_date_df = pd.merge(
        proj_ids_df, date_range_df, how='outer', on='key').drop('key', axis=1)

    # filter out downloaded
    if os.path.isfile(pickle_path):
        with open(pickle_path, 'rb') as pickle_file:
            project_attr_dict = pickle.load(pickle_file)
    else:
        project_attr_dict = {}

    index_filter = [True] * project_id_date_df.shape[0]
    project_id_date_df = project_id_date_df.set_index(['project_id', 'date'])

    for proj_id, attr_dict in project_attr_dict.items():
        for date, value in attr_dict.items():
            try:
                index = project_id_date_df.index.get_loc((proj_id, date))
                index_filter[index] = False
            except KeyError:
                continue

    del project_attr_dict

    project_id_date_df = project_id_date_df[index_filter].reset_index()
    if project_id_date_df.shape[0] == 0:
        return

    queue = mp.Queue(-1)

    def on_stop(signal, frame):
        nonlocal stopped
        stopped.value = True
        queue.put(None)

    signal.signal(signal.SIGINT, on_stop)
    signal.signal(signal.SIGTERM, on_stop)

    save_process = mp.Process(target=save_data_process,
                              args=(queue, pickle_path))
    save_process.start()

    length = project_id_date_df.shape[0]
    step = math.ceil(length / len(subscription_keys))
    download_process_list = []
    for i, index_start in enumerate(range(0, length, step)):
        index_end = index_start + step
        subscription_key = subscription_keys[i]
        batch_df = project_id_date_df.iloc[index_start: index_end]

        process = mp.Process(target=download_all_process,
                             args=(i, batch_df, url, subscription_key, queue, stopped, tqdm.get_lock()))
        process.start()
        download_process_list.append(process)

    for process in download_process_list:
        process.join()
    queue.put(None)
    save_process.join()


def main():

    stopped = mp.Value(ctypes.c_bool, False)

    for config in data_configs:
        proj_ids, date_range, pickle_path, url, subscription_key = config
        if stopped.value is True:
            break
        print(pickle_path)
        setup_download_process(proj_ids, date_range, pickle_path,
                               url, subscription_key, stopped)


if __name__ == "__main__":
    main()
