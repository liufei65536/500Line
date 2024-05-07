# repo_observer.py 
# 监视仓库的变化，当仓库发生变化时，通知调度器

import argparse
import subprocess
import os
import socket
import time
import helpers


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dispatcher-server", 
                        help="Dispatcher host:port, "\
                             "default is localhost:8888",
                             default="localhost:8888",
                             action="store")
    parser.add_argument("repo", metavar="REPO",type=str, 
                        help="The path of Repository to observe")
    return  parser.parse_args()

# poll 轮询
def poll():
    args = parse_args()
    dispatcher_host, dispatcher_port = args.dispatcher_server.split(":")

    while True:
        # 调用update_repo.sh 脚本
        # 更新仓库，检查是否有新的提交。
        # 如果有新的提交，写入包含最新提交的id到 .commit_id 文件
        try:
            subprocess.check_call(["./update_repo.sh", args.repo]) 
        except subprocess.CalledProcessError as e:
            raise Exception(f"Error updating repository: {e.output}" )
        
        # 有新的提交。通知调度、分发测试。
        if os.path.isfile(".commit_id"):
            try:
                status_response = helpers.communicate(dispatcher_host, int(dispatcher_port), 
                                              "status")
            except socket.error as e:
                raise Exception(f"Error communicating with dispatcher: {e}")
            
            if status_response == 'OK':
                commit = ""
                with open(".commit_id", "r") as f:
                    commit = f.readline()
                commit_response = helpers.communicate(dispatcher_host, int(dispatcher_port), 
                                                f"dispatch:{commit}")
                if commit_response != 'OK':
                    raise Exception(f"Could not  dispatcher the test: {commit_response}")
                print("Test dispatched!")
            else:
                raise Exception(f"Dispatcher is not ready: {status_response}")
            
            time.sleep(5)

if __name__ == "__main__":
    poll()