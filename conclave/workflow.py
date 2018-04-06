import yaml
import argparse
from typing import Callable, Dict

from conclave import generate_and_dispatch
from conclave import CodeGenConfig
from conclave.config import SharemindCodeGenConfig
from conclave.config import SparkConfig
from conclave.config import OblivcConfig
from conclave.config import NetworkConfig
from conclave.config import SwiftConfig
from conclave.swift import SwiftData


def setup(conf: Dict):

    # GENERAL
    pid = conf["pid"]
    workflow_name = conf["workflow_name"]

    # SWIFT
    cfg = conf["swift"]
    swift_config = SwiftConfig(cfg)

    # SPARK
    spark_master_url = conf["spark"]["master_url"]
    spark_config = SparkConfig(spark_master_url)

    # TODO: deprecated, not using SM anymore.
    # SHAREMIND
    sm_config = SharemindCodeGenConfig(conf["code_path"])

    # OBLIV-C
    oc_path = conf["oblivc"]["oc_path"]
    ip_port = conf["oblivc"]["ip_port"]
    oc_config = OblivcConfig(oc_path, ip_port)

    # TODO: deprecated, not using SM anymore.
    # NET
    hosts = conf["sharemind"]["parties"]
    net_config = NetworkConfig(hosts, pid)

    # CONCLAVE SYSTEM CONFIG
    conclave_config = CodeGenConfig(workflow_name) \
        .with_sharemind_config(sm_config) \
        .with_spark_config(spark_config) \
        .with_oc_config(oc_config) \
        .with_swift_config(swift_config) \
        .with_network_config(net_config)

    conclave_config.pid = pid
    conclave_config.name = workflow_name

    # TODO hardcode these three lines, will be constant on OS containers.
    conclave_config.code_path = "{0}/{1}".format(conf["code_path"], workflow_name)
    conclave_config.input_path = "{0}/{1}-in/".format(conf["input_path"], conf["name"])
    conclave_config.output_path = "{0}/{1}-out/".format(conf["output_path"], conf["name"])

    return conclave_config


def download_data(conclave_config):
    """
    Download data from Swift to local filesystem.
    """

    swift_cfg = conclave_config.system_configs['swift']['source']
    data_dir = conclave_config['input_path']
    container = swift_cfg['DATA']['container_name']
    files = swift_cfg['DATA']['files']

    swift_data = SwiftData(swift_cfg)

    for file in files:
        swift_data.get_data(container, file, data_dir)

    swift_data.close_connection()


def post_data(conclave_config):
    """
    Store locally held data on Swift.
    """

    swift_cfg = conclave_config.system_configs['swift']['destination']
    data_dir = conclave_config['input_path']
    container = swift_cfg['DATA']['container_name']
    files = swift_cfg['DATA']['files']

    swift_data = SwiftData(swift_cfg)

    for file in files:
        swift_data.put_data(container, file, data_dir)

    swift_data.close_connection()


def run(protocol: Callable):
    """
    Load parameters from config, download data from Swift,
    dispatch computation, and push results back to Swift.
    """
    parser = argparse.ArgumentParser(description="Run new workflow for Conclave.")
    parser.add_argument("--conf", metavar="/config/file.yml", type=str,
                        help="path of the config file", default="conf-ca.yml", required=False)

    args = parser.parse_args()

    with open(args.conf) as fp:
        conf = yaml.load(fp)

    conclave_config = setup(conf)

    download_data(conclave_config)
    generate_and_dispatch(protocol, conclave_config, ["sharemind"], ["spark"])
    post_data(conclave_config)


