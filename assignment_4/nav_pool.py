import json
import requests
import pandas as pd
from tqdm.autonotebook import tqdm
import pickle
from multiprocessing import Pool, TimeoutError
import multiprocessing as mp

import signal
import sys
import os

FUND_DAILY_INFO_SUBSCRIPTION_KEY = 'f95b4cdf3e884009b09c8b25d1900faf'


def download_nav(project_id, date):
    # 01. NAV กองทุนรวมรายวัน
    nav_url = 'https://api.sec.or.th/FundDailyInfo/{proj_id}/dailynav/{nav_date}'
    # Request headers
    headers = {
        'Ocp-Apim-Subscription-Key': FUND_DAILY_INFO_SUBSCRIPTION_KEY,
    }

    res = requests.get(nav_url.format(
        proj_id=project_id, nav_date=date), headers=headers)
    if res.status_code == 200:
        return res.json()
    else:
        return None


def download_nav_map(args):
    project_id, date = args
    return download_nav(project_id, date)


def main():
    stopped = False

    def on_stop(signal, frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGINT, on_stop)
    signal.signal(signal.SIGTERM, on_stop)

    amc_project_df = pd.read_csv('amc_project.csv')
    amc_project_df = amc_project_df[amc_project_df['management_style'] == 'AM']
    amc_project_df = amc_project_df.reset_index()

    date_range = pd.date_range(
        start="2020-01-01", end="2020-04-01", freq='D').astype(str)

    pickle_path = 'project_nav_dict.pickle'

    if os.path.isfile(pickle_path):
        with open(pickle_path, 'rb') as pickle_file:
            project_nav_dict = pickle.load(pickle_file)
    else:
        project_nav_dict = {}

    def save_project_nav_dict():
        with open(pickle_path, 'wb') as pickle_file:
            pickle_file.write(pickle.dumps(project_nav_dict))

    # start 4 worker processes
    proc_num = mp.cpu_count()
    # proc_num = 8
    with Pool(processes=proc_num) as pool:
        # for index, row in tqdm(amc_project_df.iloc[0:3].iterrows(), total=amc_project_df.shape[0], desc='All projects'):
        for index, row in tqdm(amc_project_df.iterrows(), total=amc_project_df.shape[0], desc='All projects'):
            amc_id = row['amc_id']
            project_id = row['project_id']

            date_nav_dict = project_nav_dict.get(project_id, {})

            date_range_filtered = [
                v for v in date_range if v not in date_nav_dict.keys()]

            if len(date_range_filtered) == 0:
                continue

            date_step = proc_num * 3
            # date_step = 10
            for date_index in tqdm(range(0, len(date_range_filtered), date_step), desc='Project {}'.format(project_id)):
                date_index_end = date_index + date_step
                date_range_batch = list(
                    date_range_filtered[date_index:date_index_end])

                date_range_batch = [
                    v for v in date_range_batch if v not in date_nav_dict.keys()]

                args = zip([project_id] * len(date_range_batch),
                           date_range_batch)

                for i, value in enumerate(pool.imap(download_nav_map, args)):
                    if value is None:
                        continue
                    date = date_range_batch[i]
                    date_nav_dict[date] = value

                if stopped is True:
                    project_nav_dict[project_id] = date_nav_dict
                    save_project_nav_dict()
                    sys.exit(0)

            project_nav_dict[project_id] = date_nav_dict
            save_project_nav_dict()

    save_project_nav_dict()


if __name__ == "__main__":
    main()
