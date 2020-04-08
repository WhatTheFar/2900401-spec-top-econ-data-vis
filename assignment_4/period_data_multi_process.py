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

FUND_FACT_SHEET_SUBSCRIPTION_KEY = '886c69c66f8f4f2b9159a2877cb4dca4'
FUND_DAILY_INFO_SUBSCRIPTION_KEY = 'f95b4cdf3e884009b09c8b25d1900faf'


def download_process(proc_num, df, url, subscription_key, queue, stopped, tqdm_lock):
    tqdm.set_lock(tqdm_lock)
    # Request headers
    headers = {
        'Ocp-Apim-Subscription-Key': subscription_key,
    }
    session = requests.Session()

    for index, row in tqdm(df.iterrows(), total=df.shape[0], desc='Process {} : all projects'.format(proc_num+1), position=proc_num):
        proj_id = row['project_id']
        date = row['date']

        # 'https://api.sec.or.th/FundDailyInfo/{proj_id}/dailynav/{date}'
        res = session.get(url.format(
            proj_id=proj_id, date=date), headers=headers)
        if res.status_code == 200:
            data = res.json()
            queue.put((proj_id, date, data))
        else:
            queue.put((proj_id, date, None))

        if stopped.value is True:
            break


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


def download_data(proj_ids, date_range, pickle_path, url, subscription_key, stopped):
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

    proc_num = mp.cpu_count()
    # proc_num = 8
    length = project_id_date_df.shape[0]
    step = math.ceil(length / proc_num)
    download_process_list = []
    for i, index_start in enumerate(range(0, length, step)):
        index_end = index_start + step
        batch_df = project_id_date_df.iloc[index_start: index_end]

        process = mp.Process(target=download_process,
                             args=(i, batch_df, url, subscription_key, queue, stopped, tqdm.get_lock()))
        process.start()
        download_process_list.append(process)

    for process in download_process_list:
        process.join()
    queue.put(None)
    save_process.join()


def main():
    FUND_FACT_SHEET_SUBSCRIPTION_KEY = '886c69c66f8f4f2b9159a2877cb4dca4'
    FUND_DAILY_INFO_SUBSCRIPTION_KEY = 'f95b4cdf3e884009b09c8b25d1900faf'

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

    data_configs = [
        # 01. NAV กองทุนรวมรายวัน
        # (project_for_nav_df['project_id'],
        #  cal_date_range(), 'project_nav_dict.pickle', 'https://api.sec.or.th/FundDailyInfo/{proj_id}/dailynav/{date}', FUND_DAILY_INFO_SUBSCRIPTION_KEY),
        # 01. NAV กองทุนรวมรายวัน
        # (project_for_nav_df['project_id'],
        #  pd.date_range(start="2017-01-01", end="2020-04-01", freq='D').astype(str), 'project_nav_dict.pickle', 'https://api.sec.or.th/FundDailyInfo/{proj_id}/dailynav/{date}', FUND_DAILY_INFO_SUBSCRIPTION_KEY),
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
        download_data(proj_ids, date_range, pickle_path,
                      url, subscription_key, stopped)


if __name__ == "__main__":
    main()
