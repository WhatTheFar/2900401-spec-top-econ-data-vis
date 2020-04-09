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

from subscription_key import FUND_DAILY_INFO_SUBSCRIPTION_KEY_AI_PRI, FUND_FACT_SHEET_SUBSCRIPTION_KEY_AI_PRI


def load_pickle(path):
    with open(path, 'rb') as pickle_file:
        return pickle.load(pickle_file)


class RateLimiter:
    """Rate limits an HTTP client that would make get() and post() calls.
    Calls are rate-limited by host.
    https://quentin.pradet.me/blog/how-do-you-rate-limit-calls-with-aiohttp.html
    This class is not thread-safe."""
    RATE = 5  # one request per second
    MAX_TOKENS = 1500

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
            return None


async def download_limit(session, limit, url, proj_id, date):
    async with limit:
        async with session.get(url.format(proj_id=proj_id, date=date)) as response:
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
                return None


async def download_all(proj_ids, date_range, pickle_path, url, subscription_key, stopped):
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

    # del project_attr_dict

    project_id_date_df = project_id_date_df[index_filter].reset_index()
    if project_id_date_df.shape[0] == 0:
        return

    def on_stop(signal, frame):
        nonlocal stopped
        stopped.value = True

    signal.signal(signal.SIGINT, on_stop)
    signal.signal(signal.SIGTERM, on_stop)

    headers = {
        'Ocp-Apim-Subscription-Key': subscription_key,
    }

    # limit = asyncio.Semaphore(1)

    async with aiohttp.ClientSession(headers=headers) as session:
        session = RateLimiter(session)
        step = 10000
        for start_index in tqdm(range(0, project_id_date_df.shape[0], step), desc='All'):
            end_index = start_index + step
            batch_df = project_id_date_df.iloc[start_index:end_index]
            tasks = []
            for index, row in tqdm(batch_df.iterrows(), total=batch_df.shape[0], leave=False):
                # for index, row in batch_df.iterrows():
                if stopped.value is True:
                    break
                proj_id = row['project_id']
                date = row['date']
                # task = asyncio.ensure_future(
                #     download_limit(session, limit, url, proj_id, date))
                task = asyncio.ensure_future(
                    download(session, url, proj_id, date))
                tasks.append(task)
            if stopped.value is not True:
                for f in tqdm(asyncio.as_completed(tasks), total=len(tasks)):
                    if stopped.value is True:
                        break
                    data = await f
                    if data is None:
                        continue

                    proj_id, date, data = data
                    attr_dict = project_attr_dict.get(proj_id, {})
                    attr_dict[date] = data
                    project_attr_dict[proj_id] = attr_dict

            if stopped.value is True:
                break
        with open(pickle_path, 'wb') as pickle_file:
            pickle_file.write(pickle.dumps(project_attr_dict))


def main():
    FUND_DAILY_INFO_SUBSCRIPTION_KEY_AI_PRI = FUND_DAILY_INFO_SUBSCRIPTION_KEY_AI_PRI
    FUND_FACT_SHEET_SUBSCRIPTION_KEY = FUND_FACT_SHEET_SUBSCRIPTION_KEY_AI_PRI

    amc_project_df = pd.read_csv('amc_project.csv')

    # am_filter = (amc_project_df.management_style == 'AM') & (
    #     amc_project_df.fund_status == 'RG') & (amc_project_df.policy_desc == 'ตราสารทุน')
    am_filter = (amc_project_df.management_style == 'AM') & (
        amc_project_df.fund_status == 'RG')
    # pm_filter = (amc_project_df.management_style == 'PM') & (
    #     amc_project_df.fund_status == 'RG') & (amc_project_df.policy_desc == 'ตราสารทุน')
    pm_filter = (amc_project_df.management_style == 'PM') & (
        amc_project_df.fund_status == 'RG')

    project_for_nav_df = amc_project_df.where(
        am_filter | pm_filter).dropna().reset_index()
    project_for_fund_full_port_df = amc_project_df.where(
        am_filter).dropna().reset_index()
    project_for_fund_top5_df = amc_project_df.where(
        am_filter).dropna().reset_index()

    PM_SET50_proj_ids = []

    project_benchmark_dict = load_pickle('project_benchmark_dict.pickle')
    amc_project_df = amc_project_df.set_index('project_id')

    for key, value in tqdm(project_benchmark_dict.items()):
        project_id = key
        bm_list = value
        amc = amc_project_df.loc[project_id]
        policy_desc = amc['policy_desc']
        fund_status = amc['fund_status']
        management_style = amc['management_style']

    #     if management_style == 'PM' and fund_status == 'RG' and policy_desc == 'ตราสารทุน':
        if management_style == 'PM' and fund_status == 'RG':
            for bm in bm_list:
                if bm['benchmark'] == 'ดัชนีผลตอบแทนรวม SET 50 (SET50 TRI)':
                    PM_SET50_proj_ids.append(project_id)
                    break

    amc_project_df = amc_project_df.reset_index()
    del project_benchmark_dict

    data_configs = [
        # 01. NAV กองทุนรวมรายวัน
        # (project_for_nav_df.iloc[:]['project_id'],
        #  cal_date_range(), 'project_nav_dict2.pickle', 'https://api.sec.or.th/FundDailyInfo/{proj_id}/dailynav/{date}', FUND_DAILY_INFO_SUBSCRIPTION_KEY),
        # 01. NAV กองทุนรวมรายวัน
        # (project_for_nav_df['project_id'],
        #  pd.date_range(start="2017-01-01", end="2020-04-01", freq='D').astype(str), 'project_nav_dict2.pickle', 'https://api.sec.or.th/FundDailyInfo/{proj_id}/dailynav/{date}', FUND_DAILY_INFO_SUBSCRIPTION_KEY),
        # 01. NAV กองทุนรวมรายวัน
        # (PM_SET50_proj_ids,
        #  pd.date_range(start="2017-01-01", end="2020-04-01", freq='D').astype(str), 'project_nav_pm_dict.pickle', 'https://api.sec.or.th/FundDailyInfo/{proj_id}/dailynav/{date}', FUND_DAILY_INFO_SUBSCRIPTION_KEY_FAR_OFFICIAL_2_PRI),
        # (['M0132_2557'],
        #  pd.date_range(start="2017-01-01", end="2020-04-01", freq='D').astype(str), 'project_nav_pm_dict.pickle', 'https://api.sec.or.th/FundDailyInfo/{proj_id}/dailynav/{date}', FUND_DAILY_INFO_SUBSCRIPTION_KEY),
        # 28. สัดส่วนของการลงทุนของกองทุนรวม
        # (project_for_fund_full_port_df['project_id'], cal_month_range(),
        #  'project_fund_full_port_dict.pickle', 'https://api.sec.or.th/FundFactsheet/fund/{proj_id}/FundFullPort/{date}', FUND_FACT_SHEET_SUBSCRIPTION_KEY),
        # 29. หลักทรัพย์ 5 อันดับแรกที่ลงทุน
        # (project_for_fund_top5_df['project_id'], cal_month_range(),
        #  'project_fund_top5_dict.pickle', 'https://api.sec.or.th/FundFactsheet/fund/{proj_id}/FundTop5/{date}', FUND_FACT_SHEET_SUBSCRIPTION_KEY),
    ]

    stopped = mp.Value(ctypes.c_bool, False)

    for config in data_configs:
        proj_ids, date_range, pickle_path, url, subscription_key = config
        if stopped.value is True:
            break
        print(pickle_path)
        asyncio.get_event_loop().run_until_complete(download_all(proj_ids, date_range, pickle_path,
                                                                 url, subscription_key, stopped))


if __name__ == "__main__":
    main()
