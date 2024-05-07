# 调度器，侦听测试运行程序和观察者的请求。
# 允许测试运行程序注册自己，然后将测试分配给它们。

import argparse
import time
import os
import socket
import threading
import socketserver  
import re

import helpers


class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    '''多线程TCP服务器。使用MixIn方式实现'''
    runners = [] # 追踪 test runner pool
    dead = False # Indicate to other threads that we are no longer running
    dispatched_commits = {} # Keeps track of commits we dispatched
    pending_commits = [] # Keeps track of commits we have yet to dispatch


class DispatcherHandler(socketserver.BaseRequestHandler):
    """
    调度程序的RequestHandler类。
    根据传入的提交分派测试运行器，并处理它们的请求和测试结果(self.request)。
    """
    command_re = re.compile(r"(\w+)(:.+)*")
    BUF_SIZE = 1024
    def handle(self):
        self.data = self.request.recv(self.BUF_SIZE).decode('utf-8').strip()
        command_groups = self.command_re.match(self.data)
        if not command_groups:
            self.request.sendall("Invalid command".encode("utf-8"))
            return
        command = command_groups.group(1)
        if command == "status":  
            print("in status")
            self.request.sendall("OK".encode("utf-8"))
        elif command == "register":
            # Add this test runner to our pool
            print("register")
            address = command_groups.group(2)
            host, port = re.findall(r":(\w*)", address)
            runner = {"host": host, "port":port}
            self.server.runners.append(runner)
            self.request.sendall("OK".encode("utf-8"))
        elif command == "dispatch":
            print ("going to dispatch")
            commit_id = command_groups.group(2)[1:]
            if not self.server.runners:
                self.request.sendall("No runners are registered".encode("utf-8"))
            else:
                # The coordinator can trust us to dispatch the test
                self.request.sendall("OK".encode("utf-8"))
                dispatch_tests(self.server, commit_id)
        elif command == "results":
            print("got test results")
            results = command_groups.group(2)[1:]
            results = results.split(":")
            commit_id = results[0]
            length_msg = int(results[1])
            # 3 is the number of ":" in the sent command
            remaining_buffer = self.BUF_SIZE - \
                (len(command) + len(commit_id) + len(results[1]) + 3)
            if length_msg > remaining_buffer:
                self.data += self.request.recv(length_msg - remaining_buffer).strip()
            del self.server.dispatched_commits[commit_id]
            if not os.path.exists("test_results"):
                os.makedirs("test_results")
            with open("test_results/%s" % commit_id, "w") as f:
                data = self.data.split(":")[3:]
                data = "\n".join(data)
                f.write(data)
            self.request.sendall("OK".encode("utf-8"))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host",
                        help="dispatcher's host, by default it uses localhost",
                        default="localhost",
                        action="store")
    parser.add_argument("--port",
                        help="dispatcher's port, by default it uses 8888",
                        default=8888,
                        action="store")
    return parser.parse_args()


def serve():
    args = parse_args()
    server = ThreadingTCPServer((args.host, int(args.port)), DispatcherHandler)
    print(f"serving on {args.host}:{int(args.port)}")  

    def runner_checker(server):
        '''通过ping 检查测试运行程序是否在线'''
        def manage_commit_lists(runner):
            #py2-> py3: dict.iteritems()--> dict.items() 
            for commit, assigned_runner in server.dispatched_commits.items():  
                if assigned_runner == runner:
                    del server.dispatched_commits[commit]
                    server.pending_commits.append(commit)
                    break
            server.runners.remove(runner)
        while not server.dead:
            time.sleep(1)
            for runner in server.runners:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    response = helpers.communicate(runner["host"],
                                                   int(runner["port"]),
                                                   "ping")
                    if response != "pong":
                        print(f"removing runner {runner}" )
                        manage_commit_lists(runner)
                except socket.error as e:
                    manage_commit_lists(runner)


    def redistribute(server):
        '''重新分配测试'''
        while not server.dead:
            for commit in server.pending_commits:
                print("running redistribute")
                print(server.pending_commits)
                dispatch_tests(server, commit)
                time.sleep(5)


    runner_heartbeat = threading.Thread(target=runner_checker, args=(server,))
    redistributor = threading.Thread(target=redistribute, args=(server,))
    try:
        runner_heartbeat.start()
        redistributor.start()
        # serve forever  
        server.serve_forever()
    except (KeyboardInterrupt, Exception):
        # if any exception occurs, kill the thread
        server.dead = True
        runner_heartbeat.join()
        redistributor.join()

    

    

def dispatch_tests(server, commit_id):
    '''分配测试'''
    # NOTE: usually we don't run this forever
    while True:
        print("trying to dispatch to runners")
        for runner in server.runners:
            response = helpers.communicate(runner["host"], int(runner["port"]),
                                           f"runtest:{commit_id}")
            if response == "OK":
                print(f"adding id {commit_id}")
                server.dispatched_commits[commit_id] = runner
                if commit_id in server.pending_commits:
                    server.pending_commits.remove(commit_id)
                return
        time.sleep(2)

if __name__ == "__main__":
    serve()