from bson.son import SON
import pandas as pd
import numpy as np

from queries.query_util import df_aggregate, utility, const

def load_df_by_slot(suite,exp):

    results = utility.get_result_collection(suite)

    pipeline = _build_pipeline(exp)
    cursor = results.aggregate(pipeline, allowDiskUse=True)

    df =  pd.DataFrame(list(cursor))

    return df

def load_df_by_rep(suite, exp):

    df = load_df_by_slot(suite,exp)

    config_cols = ["rep", "slot", "data_origin", "op_type", "num_clients", "n_server_vm", "n_client_vm", "n_vc", "workload", "workload_ratio",
            "multi_get_behaviour", "multi_get_size", "n_worker_per_mw", "n_middleware_vm", "n_instances_mt_per_machine", "n_threads_per_mt_instance",
            "write_bandwidth_limit","bandwidth_limit_write_throughput","bandwidth_limit_write_per_server_throughput", "read_bandwidth_limit", "bandwidth_limit_read_throughput", "client_rtt", "server_rtt"]

    value_cols = ["throughput", "rt_mean", "rt_std", "qwt_mean", "qwt_std", "ntt_mean", "ntt_std", "wtt_mean", "wtt_std",
            "tsst_mean", "tsst_std", "sst0_mean", "sst0_std", "sst0count", "sst1_mean", "sst1_std", "sst1count", "sst2_mean", "sst2_std", "sst2count", "sst_mean", "sst_std", "sstmax", "queue_size_mean", "arrivalrate"]


    df = df.set_index(config_cols, drop=False)
    df_slot, config_cols_slot, value_cols_slot = df_aggregate.aggregate_slots(df, config_cols=config_cols, value_cols=value_cols)

    return df_slot, config_cols_slot, value_cols_slot

def load_df(suite, exp):
    df_slot, config_cols_slot, value_cols_slot = load_df_by_rep(suite, exp)

    df_slot["tp_cov"] = df_slot.apply(lambda row: row['throughput_slot_std'] / row['throughput_slot_mean'], axis=1)

    #df_slot = df_slot[df_slot["tp_cov"]<const.cov_threshold]

    df_rep, config_cols_rep, value_cols_rep = df_aggregate.aggregate_repetitions(df_slot, config_cols=config_cols_slot, value_cols=value_cols_slot)

    df_rep = df_rep.reset_index()

    df_rep['nt_util'] = df_rep.apply(lambda row: row['throughput_rep_mean'] * row['ntt_rep_mean'] / 1000 ,axis=1)
    df_rep['s_util'] = df_rep.apply(lambda row: (row['throughput_rep_mean'] * row['sst_rep_mean']/1000)/(row['n_middleware_vm']*row['n_worker_per_mw']) ,axis=1)
    df_rep['s0_util'] = df_rep.apply(lambda row: (row['throughput_rep_mean'] * row['sst0_rep_mean']/1000)/(row['n_middleware_vm']*row['n_worker_per_mw']) ,axis=1)
    df_rep['s1_util'] = df_rep.apply(lambda row: (row['throughput_rep_mean'] * row['sst1_rep_mean']/1000)/(row['n_middleware_vm']*row['n_worker_per_mw']) ,axis=1)
    df_rep['s2_util'] = df_rep.apply(lambda row: (row['throughput_rep_mean'] * row['sst2_rep_mean']/1000)/(row['n_middleware_vm']*row['n_worker_per_mw']) ,axis=1)
    df_rep['wt_util'] = df_rep.apply(lambda row: (row['throughput_rep_mean'] * (row['wtt_rep_mean']-row['sst_rep_mean']) / 1000)/(row['n_middleware_vm']*row['n_worker_per_mw']),axis=1)
    df_rep['wt_sstmax_util'] = df_rep.apply(lambda row: (row['throughput_rep_mean'] * (row['wtt_rep_mean']-row['sstmax_rep_mean']) / 1000)/(row['n_middleware_vm']*row['n_worker_per_mw']),axis=1)
    df_rep['wttotal_util'] = df_rep.apply(lambda row: (row['throughput_rep_mean'] * (row['wtt_rep_mean']) / 1000)/(row['n_middleware_vm']*row['n_worker_per_mw']),axis=1)

    return df_rep


def _build_pipeline(exp):
    stats_window_size = 5.0 #seconds
    value_size = 4096 # bytes
    value_size_mbit = value_size / 125000.0

    exp_ext = exp + "ext"

    pipeline = [
        {"$match": {"$or": [ {"exp": exp }, {"exp": exp_ext } ]}},
        {"$addFields":{"num_clients": {"$multiply": ["$exp_config.n_client",
                                                     "$exp_config.n_instances_mt_per_machine",
                                                     "$exp_config.n_threads_per_mt_instance",
                                                     "$exp_config.n_vc"
                                                    ]},
                        "workload": {"$switch": {"branches": [  { "case": {"$eq":["$exp_config.workload_ratio", "1:0"]}, "then": "write-only" },
                                                                { "case": {"$eq":["$exp_config.workload_ratio", "0:1"]}, "then": "read-only" },],
                                                "default": "read-write"}},
                        "from_client_netstat": {"$reduce": {
                                                    "input": {"$filter":{"input": "$network_stats", "as": "e", "cond": {"$eq":[{ "$substrBytes": ["$$e.from", 0, 1]},"C"]}}},
                                                    "initialValue":{"bandwidth": 0.0,
                                                                     "rtt": 0.0,
                                                                     "count":0},
                                                    "in":{ "bandwidth": {"$add" : ["$$value.bandwidth", "$$this.bandwidth"]},
                                                            "rtt": {"$add" : ["$$value.rtt", {"$toDouble":"$$this.rtt"}]}, # TODO [nku] remove double conversion
                                                            "count": {"$add": ["$$value.count", 1]}}
                                                            }
                                                },
                        "to_server_netstat": {"$reduce": {
                                                    "input": {"$filter":{"input": "$network_stats", "as": "e", "cond": {"$eq":[{ "$substrBytes": ["$$e.to", 0, 1]},"S"]}}},
                                                    "initialValue":{"bandwidth": 0.0,
                                                                     "rtt": 0.0,
                                                                     "count":0},
                                                    "in": { "bandwidth": {"$add" : ["$$value.bandwidth", "$$this.bandwidth"]},
                                                            "rtt": {"$add" : ["$$value.rtt", {"$toDouble":"$$this.rtt"}]}, # TODO [nku] remove double conversion
                                                            "count": {"$add": ["$$value.count", 1]}}
                                                    }
                                                },
                        "to_client_netstat": {"$reduce": {
                                                    "input": {"$filter":{"input": "$network_stats", "as": "e", "cond": {"$eq":[{ "$substrBytes": ["$$e.to", 0, 1]},"C"]}}},
                                                    "initialValue":{"bandwidth": 0.0,
                                                                     "rtt": 0.0,
                                                                     "count":0},
                                                    "in":{ "bandwidth": {"$add" : ["$$value.bandwidth", "$$this.bandwidth"]},
                                                            "rtt": {"$add" : ["$$value.rtt", {"$toDouble":"$$this.rtt"}]}, # TODO [nku] remove double conversion
                                                            "count": {"$add": ["$$value.count", 1]}}
                                                    }
                                                },
                        "from_server_netstat": {"$reduce": {
                                                    "input": {"$filter":{"input": "$network_stats", "as": "e", "cond": {"$eq":[{ "$substrBytes": ["$$e.from", 0, 1]}, "S"]}}},
                                                    "initialValue":{"bandwidth": 0.0,
                                                                     "rtt": 0.0,
                                                                     "count":0},
                                                    "in":{ "bandwidth": {"$add" : ["$$value.bandwidth", "$$this.bandwidth"]},
                                                            "rtt": {"$add" : ["$$value.rtt", {"$toDouble":"$$this.rtt"}]}, # TODO [nku] remove double conversion
                                                            "count": {"$add": ["$$value.count", 1]}}
                                                }},
                      }
        },
        {"$addFields":{"write_bandwidth_limit": {"$min":["$from_client_netstat.bandwidth", "$to_server_netstat.bandwidth"]},
                       "write_bandwidth_limit_per_server": {"$min":["$from_client_netstat.bandwidth", {"$divide":["$to_server_netstat.bandwidth", "$exp_config.n_server"]}]},
                       "read_bandwidth_limit":  {"$min":["$from_server_netstat.bandwidth", "$to_client_netstat.bandwidth"]},
                       "client_rtt":{"$divide":["$from_client_netstat.rtt", "$from_client_netstat.count"]},
                       "server_rtt":{"$divide":["$to_server_netstat.rtt", "$to_server_netstat.count"]}
                       }
        },
        {"$unwind":"$mw_stats"},
        {"$project": {"mw_stats.rt_hist":0}},
        {"$unwind":"$mw_stats.op"},
        {"$addFields": {"queue":  { "$arrayElemAt": [ { "$filter": { "input": "$mw_stats.queue", "as": "q", "cond": {"$eq":["$$q.slot", "$mw_stats.op.slot"]} } }, 0 ]},
                        "arrival":  { "$arrayElemAt": [ { "$filter": { "input": "$mw_stats.arrival", "as": "a", "cond": {"$eq":["$$a.slot", "$mw_stats.op.slot"]} } }, 0 ]},
                        }
        }, # extract matching queue length and arrival according to slot
        {"$group": {"_id" : {"rep":"$repetition",
                             "slot": "$mw_stats.op.slot",
                             "op_type": "$mw_stats.op.op_type",
                             "num_clients": "$num_clients",
                             "n_server": "$exp_config.n_server",
                             "n_client": "$exp_config.n_client",
                             "n_vc": "$exp_config.n_vc",
                             "workload": "$workload",
                             "workload_ratio": "$exp_config.workload_ratio",
                             "multi_get_behaviour":"$exp_config.multi_get_behaviour",
                             "multi_get_size":"$exp_config.multi_get_size",
                             "n_worker_per_mw": "$exp_config.n_worker_per_mw",
                             "n_middleware" : "$exp_config.n_middleware",
                             "n_instances_mt_per_machine":"$exp_config.n_instances_mt_per_machine",
                             "n_threads_per_mt_instance":"$exp_config.n_threads_per_mt_instance"},
                   "write_bandwidth_limit":{"$avg":"$write_bandwidth_limit"}, # should all be the same anyway
                   "write_bandwidth_limit_per_server":{"$avg":"$write_bandwidth_limit_per_server"}, # should all be the same anyway
                   "read_bandwidth_limit":{"$avg":"$read_bandwidth_limit"}, # should all be the same anyway
                   "client_rtt":{"$avg":"$client_rtt"}, # should all be the same anyway
                   "server_rtt":{"$avg":"$server_rtt"}, # should all be the same anyway
                   "run_count" : {"$sum" :  1},
                   "queue_size_mean":{"$avg":"$queue.size"}, # average over mw's
                   "nt_arrival_count":{"$sum":"$arrival.arrival_count"}, # sum over mw's TODO needs to be changed because aggregate over mw AND WORKER here
                   "sum_rt_count" : {"$sum": "$mw_stats.op.rt_count"},
                   "rt_arr" :  {"$push": {"m2":"$mw_stats.op.rt_m2", "mean":"$mw_stats.op.rt_mean", "count":"$mw_stats.op.rt_count"}},
                   "qwt_arr" : {"$push": {"m2":"$mw_stats.op.qwt_m2", "mean":"$mw_stats.op.qwt_mean", "count":"$mw_stats.op.qwt_count"}},
                   "ntt_arr" : {"$push": {"m2":"$mw_stats.op.ntt_M2", "mean":"$mw_stats.op.ntt_mean", "count":"$mw_stats.op.ntt_count"}},
                   "wtt_arr" : {"$push": {"m2":"$mw_stats.op.wtt_M2", "mean":"$mw_stats.op.wtt_mean", "count":"$mw_stats.op.wtt_count"}},
                   "tsst_arr" : {"$push": {"m2":"$mw_stats.op.tsst_M2", "mean":"$mw_stats.op.tsst_mean", "count":"$mw_stats.op.tsst_count"}},
                   "sst0_arr" : {"$push": {"m2":"$mw_stats.op.sst0_M2", "mean":"$mw_stats.op.sst0_mean", "count":"$mw_stats.op.sst0_count"}},
                   "sst1_arr" : {"$push": {"m2":"$mw_stats.op.sst1_M2", "mean":"$mw_stats.op.sst1_mean", "count":"$mw_stats.op.sst1_count"}},
                   "sst2_arr" : {"$push": {"m2":"$mw_stats.op.sst2_M2", "mean":"$mw_stats.op.sst2_mean", "count":"$mw_stats.op.sst2_count"}},
                   }
        },
        {"$addFields":{ "rt": {"$reduce":  _reduce_stat("rt_arr")},
                        "qwt": {"$reduce": _reduce_stat("qwt_arr")},
                        "ntt": {"$reduce": _reduce_stat("ntt_arr")},
                        "wtt": {"$reduce": _reduce_stat("wtt_arr")},
                        "tsst": {"$reduce": _reduce_stat("tsst_arr")},
                        "sst0": {"$reduce": _reduce_stat("sst0_arr")},
                        "sst1": {"$reduce": _reduce_stat("sst1_arr")},
                        "sst2": {"$reduce": _reduce_stat("sst2_arr")}
                     }
        },
        {"$addFields": {"throughput": {"$divide" : ["$sum_rt_count", stats_window_size]},
                        "rt_mean" : "$rt.mean",
                        "rt_std":{"$sqrt": {"$divide": ["$rt.m2", {"$subtract":["$rt.count", 1]}]}},
                        "qwt_mean" : "$qwt.mean",
                        "qwt_std":{"$sqrt": {"$divide": ["$qwt.m2", {"$subtract":["$qwt.count", 1]}]}},
                        "ntt_mean" : "$ntt.mean",
                        "ntt_std":{"$sqrt": {"$divide": ["$ntt.m2", {"$subtract":["$ntt.count", 1]}]}},
                        "wtt_mean" : "$wtt.mean",
                        "wtt_std":{"$sqrt": {"$divide": ["$wtt.m2", {"$subtract":["$wtt.count", 1]}]}},
                        "tsst_mean" : "$tsst.mean",
                        "tsst_std":{"$sqrt": {"$divide": ["$tsst.m2", {"$subtract":["$tsst.count", 1]}]}},
                        "sst0_mean" : "$sst0.mean",
                        "sst0_std":{"$sqrt": {"$divide": ["$sst0.m2", {"$subtract":["$sst0.count", 1]}]}},
                        "sst1_mean" : "$sst1.mean",
                        "sst1_std":{"$sqrt": {"$divide": ["$sst1.m2", {"$subtract":["$sst1.count", 1]}]}},
                        "sst2_mean" : "$sst2.mean",
                        "sst2_std":{"$sqrt": {"$divide": ["$sst2.m2", {"$subtract":["$sst2.count", 1]}]}},
                        "sst_arr":{"$setUnion":[["$sst0"],["$sst1"],["$sst2"]]}
                       }},
        {"$addFields":{ "sst": {"$reduce":  _reduce_stat("sst_arr")},
                        "data_origin": "mw"
                    }},
        {"$project": {"_id": 0,
                        "rep":"$_id.rep",
                        "slot": "$_id.slot",
                        "op_type": "$_id.op_type",
                        "num_clients": "$_id.num_clients",
                        "n_server_vm": "$_id.n_server",
                        "n_client_vm": "$_id.n_client",
                        "n_vc": "$_id.n_vc",
                        "workload": "$_id.workload",
                        "workload_ratio": "$_id.workload_ratio",
                        "multi_get_behaviour": { "$cond": { "if": { "$eq": ["$_id.multi_get_behaviour", None]}, "then": "-", "else": "$_id.multi_get_behaviour" }},
                        "multi_get_size": { "$cond": { "if": { "$eq": ["$_id.multi_get_size", None]}, "then": "-", "else": "$_id.multi_get_size" }},
                        "n_worker_per_mw": "$_id.n_worker_per_mw",
                        "n_middleware_vm" : "$_id.n_middleware",
                        "n_instances_mt_per_machine":"$_id.n_instances_mt_per_machine",
                        "n_threads_per_mt_instance":"$_id.n_threads_per_mt_instance",
                        "run_count": 1,
                        "data_origin":1,
                        "queue_size_mean": 1,
                        "arrivalrate": {"$divide": [{"$divide" : ["$nt_arrival_count", "$_id.n_worker_per_mw"]}, stats_window_size]},
                        "throughput":1,
                        "rt_mean" : {"$divide" : ["$rt_mean", 10.0]},
                        "rt_std": {"$divide" : ["$rt_std", 10.0]},
                        "qwt_mean" : {"$divide" : ["$qwt_mean", 10.0]},
                        "qwt_std": {"$divide" : ["$qwt_std", 10.0]},
                        "ntt_mean" : {"$divide" : ["$ntt_mean", 10.0]},
                        "ntt_std": {"$divide" : ["$ntt_std", 10.0]},
                        "wtt_mean" : {"$divide" : ["$wtt_mean", 10.0]},
                        "wtt_std": {"$divide" : ["$wtt_std", 10.0]},
                        "tsst_mean" : {"$divide" : ["$tsst_mean", 10.0]},
                        "tsst_std": {"$divide" : ["$tsst_std", 10.0]},
                        "sst0_mean" : {"$divide" : ["$sst0_mean", 10.0]},
                        "sst0_std": {"$divide" : ["$sst0_std", 10.0]},
                        "sst0count":"$sst0.count",
                        "sst1_mean" :{"$divide" : ["$sst1_mean", 10.0]},
                        "sst1_std": {"$divide" : ["$sst1_std", 10.0]},
                        "sst1count":"$sst1.count",
                        "sst2_mean" : {"$divide" : ["$sst2_mean", 10.0]},
                        "sst2_std": {"$divide" : ["$sst2_std", 10.0]},
                        "sst2count":"$sst2.count",
                        "sst_mean": {"$divide" : ["$sst.mean", 10.0]},
                        "sst_std": {"$divide" : [{"$sqrt": {"$divide": ["$sst.m2", {"$subtract":["$sst.count", 1]}]}}, 10.0]},
                        "sstmax": {"$divide" : [{ "$max": ["$sst0_mean", "$sst1_mean", "$sst2_mean"]  }, 10.0]},
                        "read_bandwidth_limit": { "$cond": { "if": { "$eq": ["$read_bandwidth_limit", None]}, "then": "-", "else": "$read_bandwidth_limit" }},
                        "bandwidth_limit_read_throughput": { "$cond": { "if": { "$eq": ["$read_bandwidth_limit", None]}, "then": "-", "else": {"$divide":["$read_bandwidth_limit", value_size_mbit]}}},
                        "write_bandwidth_limit":{ "$cond": { "if": { "$eq": ["$write_bandwidth_limit", None]}, "then": "-", "else": "$write_bandwidth_limit" }},
                        "bandwidth_limit_write_throughput": { "$cond": { "if": { "$eq": ["$write_bandwidth_limit", None]}, "then": "-", "else": {"$divide":["$write_bandwidth_limit", value_size_mbit]}}},
                        "bandwidth_limit_write_per_server_throughput": { "$cond": { "if": { "$eq": ["$write_bandwidth_limit_per_server", None]}, "then": "-", "else": {"$divide":["$write_bandwidth_limit_per_server", value_size_mbit]}}},
                        "client_rtt":{ "$cond": { "if": { "$eq": ["$client_rtt", None]}, "then": "-", "else": "$client_rtt" }},
                        "server_rtt":{ "$cond": { "if": { "$eq": ["$server_rtt", None]}, "then": "-", "else": "$server_rtt" }},
                     }
        },
        {"$match":{ "throughput": { "$gt": 0 }}},
        {"$sort":SON([("n_client_vm",1),
                        ("n_middleware_vm",1),
                        ("n_server_vm",1),
                        ("workload",1),
                        ("multi_get_behaviour",1),
                        ("multi_get_size",1),
                        ("n_worker_per_mw",1),
                        ("num_clients", 1),
                        ("rep",1),
                        ("slot", 1)])},
    ]

    return pipeline


def _reduce_stat(arr):
    """
    builds a dictionary for the pymongo $reduce operation to reduce a list of (mean, count, m2) triples
    according to the algorithm described in:
    https://en.wikipedia.org/wiki/Algorithms_for_calculating_variance#Parallel_algorithm
    """
    d = {"input": {"$filter": {"input": f"${arr}",
                                                                    "as":"x",
                                                                    "cond":{"$gt":["$$x.count", 0.0]}
                                                                   }
                                                       },
                                            "initialValue": {"mean": 0.0,
                                                             "count": 0,
                                                             "m2":0.0},
                                            "in": {"mean":{"$sum":["$$value.mean",
                                                                    {"$multiply":[{"$subtract": [{"$toDouble":"$$this.mean"}, "$$value.mean"]},
                                                                                  {"$divide":["$$this.count",
                                                                                              {"$sum":["$$this.count","$$value.count"]}]}
                                                                                 ]
                                                                    }
                                                                  ]},
                                                   "m2" : {"$sum" : ["$$value.m2",
                                                                        "$$this.m2",
                                                                        {"$multiply": [
                                                                                        {"$pow":[
                                                                                            {"$subtract": [
                                                                                                "$$this.mean",
                                                                                                "$$value.mean"]
                                                                                            }, 2]
                                                                                        },
                                                                                       {"$divide": [
                                                                                           {"$multiply": [
                                                                                               "$$value.count",
                                                                                               "$$this.count"
                                                                                           ]},
                                                                                            {"$sum": [
                                                                                                "$$value.count",
                                                                                                "$$this.count"
                                                                                            ]}
                                                                                       ]}
                                                                        ]}
                                                                  ]},
                                                   "count": {"$sum":["$$value.count", "$$this.count"]},
                                                  }
                                             }
    return d
