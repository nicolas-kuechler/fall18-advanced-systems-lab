import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import os

from plots import const

def nc(ax, df):

    n_workers = df.loc[:,'n_worker_per_mw'].unique()
    assert(n_workers.shape[0]==1)

    clients = df.loc[:,'num_clients'].values
    nt_utils = df.loc[:,'nt_util'].values * 100
    wt_utils = df.loc[:,'wt_util'].values * 100

    if df['workload'].unique()[0] == 'write-only':
        s0_utils = df.loc[:,'s0_util'].values * 100
        s1_utils = df.loc[:,'s1_util'].values * 100
        s2_utils = df.loc[:,'s2_util'].values * 100

        s_utils = np.maximum.reduce([s0_utils,s1_utils,s2_utils])
    else:
        s_utils = df.loc[:,'s_util'].values * 100

    # plot net-thread utilization
    ax.plot(clients, nt_utils, color=const.rt_component_color['ntt'],
                                marker='.',
                                markersize=const.markersize,
                                label="net-thread decoding")

    ax.plot(clients, wt_utils, color=const.rt_component_color['wtt'],
                                marker='.',
                                markersize=const.markersize,
                                label="worker-thread processing")

    ax.plot(clients, s_utils, color=const.rt_component_color['sst'],
                                marker='.',
                                markersize=const.markersize,
                                label="worker-thread server service time")

    # TODO [nku] decide on legend
    ax.legend()
    ax.set_ylabel('Utilization in %')
    ax.set_xlabel(const.axis_label['number_of_clients'])

    ax.set_xlim(0, clients[-1]+2)
    ax.set_ylim(0, 100)
    ax.set_xticks(clients)

def detail_nc(ax, df):

    n_workers = df.loc[:,'n_worker_per_mw'].unique()
    assert(n_workers.shape[0]==1)

    clients = df.loc[:,'num_clients'].values
    nt_utils = df.loc[:,'nt_util'].values * 100

    wttotal_utils = df.loc[:,'wttotal_util'].values * 100

    if df['workload'].unique()[0] == 'write-only':
        s0_utils = df.loc[:,'s0_util'].values * 100
        s1_utils = df.loc[:,'s1_util'].values * 100
        s2_utils = df.loc[:,'s2_util'].values * 100

        s_utils = np.maximum.reduce([s0_utils,s1_utils,s2_utils])
        wt_utils = df.loc[:,'wt_sstmax_util'].values * 100

    else:
        wt_utils = df.loc[:,'wt_util'].values * 100
        s_utils = df.loc[:,'s_util'].values * 100

    # plot net-thread utilization
    ax.plot(clients, nt_utils, color=const.rt_component_color['ntt'],
                                marker='.',
                                markersize=const.markersize,
                                label="net-thread decoding")

    ax.plot(clients, wt_utils, color=const.rt_component_color['wtt'],
                                marker='.',
                                markersize=const.markersize,
                                label="worker-thread processing")



    ax.plot(clients, s0_utils, color=const.sst_color['sst0'],
                                marker='.',
                                markersize=const.markersize,
                                label="worker-thread server 1 service time")

    ax.plot(clients, s1_utils, color=const.sst_color['sst1'],
                                marker='.',
                                markersize=const.markersize,
                                label="worker-thread server 2 service time")

    ax.plot(clients, s2_utils, color=const.sst_color['sst2'],
                                marker='.',
                                markersize=const.markersize,
                                label="worker-thread server 3 service time")

    ax.plot(clients, wttotal_utils, color="grey",
                                    marker='.',
                                    markersize=const.markersize,
                                    label="worker-thread total time")

     #	wt_util 	s_util 	s0_util 	s1_util 	s2_util

    # TODO [nku] decide on legend
    ax.legend()
    ax.set_ylabel('Utilization in %')
    ax.set_xlabel(const.axis_label['number_of_clients'])

    ax.set_xlim(0, clients[-1]+2)
    ax.set_ylim(0, 100)
    ax.set_xticks(clients)
