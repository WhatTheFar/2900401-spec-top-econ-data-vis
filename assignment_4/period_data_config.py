import pandas as pd
import pickle

from subscription_key import fund_daily_subscription_keys, fund_fact_subscription_keys


def load_pickle(path):
    with open(path, 'rb') as pickle_file:
        return pickle.load(pickle_file)


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
    # years = ['2019', '2018', '2017', '2016', '2015']
    years = ['2019']
    months = ['01', '02', '03', '04', '05',
              '06', '07', '08', '09', '10', '11', '12']
    date_range = ['202001', '202002', '202003']

    for year in years:
        for month in months:
            date_range.append(year + str(month))

    return date_range


amc_project_df = pd.read_csv('csv/amc_project.csv')

# am_filter = (amc_project_df.management_style == 'AM') & (
#     amc_project_df.fund_status == 'RG') & (amc_project_df.policy_desc == 'ตราสารทุน')
am_filter = (amc_project_df.management_style == 'AM') & (
    amc_project_df.fund_status == 'RG')
# pm_filter = (amc_project_df.management_style == 'PM') & (
#     amc_project_df.fund_status == 'RG') & (amc_project_df.policy_desc == 'ตราสารทุน')
pm_filter = (amc_project_df.management_style == 'PM') & (
    amc_project_df.fund_status == 'RG')

project_for_nav_df = amc_project_df.where(
    am_filter).dropna().reset_index()
project_for_fund_full_port_df = amc_project_df.where(
    am_filter).dropna().reset_index()
project_for_fund_top5_df = amc_project_df.where(
    am_filter).dropna().reset_index()

PM_SET50_proj_ids = []

project_benchmark_dict = load_pickle(
    'pickle/project_benchmark_dict.pickle')
amc_project_df = amc_project_df.set_index('project_id')

for key, value in project_benchmark_dict.items():
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
    #  cal_date_range(), 'pickle/project_nav_dict2.pickle', 'https://api.sec.or.th/FundDailyInfo/{proj_id}/dailynav/{date}', fund_daily_subscription_keys),
    # 01. NAV กองทุนรวมรายวัน
    # (project_for_nav_df['project_id'],
    #  pd.date_range(start="2017-01-01", end="2020-04-01", freq='D').astype(str), 'pickle/project_nav_dict3.pickle', 'https://api.sec.or.th/FundDailyInfo/{proj_id}/dailynav/{date}', fund_daily_subscription_keys),
    # (project_for_nav_df['project_id'],
    #  pd.date_range(start="2020-01-01", end="2020-04-01", freq='D').astype(str), 'pickle/project_nav_dict3.pickle', 'https://api.sec.or.th/FundDailyInfo/{proj_id}/dailynav/{date}', fund_daily_subscription_keys),

    # 01. NAV กองทุนรวมรายวัน
    # (PM_SET50_proj_ids,
    #  pd.date_range(start="2017-01-01", end="2020-04-01", freq='D').astype(str), 'pickle/project_nav_pm_dict.pickle', 'https://api.sec.or.th/FundDailyInfo/{proj_id}/dailynav/{date}', fund_daily_subscription_keys),
    (PM_SET50_proj_ids,
     pd.date_range(start="2010-01-01", end="2020-04-01", freq='D').astype(str), 'pickle/project_nav_pm_dict2.pickle', 'https://api.sec.or.th/FundDailyInfo/{proj_id}/dailynav/{date}', fund_daily_subscription_keys),

    # 28. สัดส่วนของการลงทุนของกองทุนรวม
    # (project_for_fund_full_port_df['project_id'], cal_month_range(),
    #  'pickle/project_fund_full_port_dict2.pickle', 'https://api.sec.or.th/FundFactsheet/fund/{proj_id}/FundFullPort/{date}', fund_fact_subscription_keys),

    # 29. หลักทรัพย์ 5 อันดับแรกที่ลงทุน
    # (project_for_fund_top5_df['project_id'], cal_month_range(),
    #  'pickle/project_fund_top5_dict2.pickle', 'https://api.sec.or.th/FundFactsheet/fund/{proj_id}/FundTop5/{date}', fund_fact_subscription_keys),
]
