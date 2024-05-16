# 什么是持续集成系统？
在软件开发过程中，我们通过**测试**验证代码是否按照预期工作。
持续集成系统(CI)用于测试新代码。提交代码后，CI将验证新提交能否通过测试。
因此，CI系统需要获取新更改、允许测试、生成报告。本项目将演示一个小型的、分布式的CI，该系统具有可扩展性。

# 介绍
CI具有三个组件：
- 观察者（observer）：监视代码存储库。如果代码更改了，就通知调度器。
- 调度 （dispatcher）：寻找合适的测试执行程序。
- 测试执行（test runner）：执行测试。

这三个组件可以通过很多方式结合，例如，同时在一个/多个机器上的一个进程/多个进程。
这个项目中，这些组件中的每一个都是自己的过程。这将使每个进程独立于其他进程，并让我们运行每个进程的多个实例。
此外，进程间还通过套接字进行通信，这将使我们能够在单独的网络机器上运行每个进程。为每个组件分配一个唯一的主机/端口地址，每个进程都可以通过在分配的地址上发布消息来与其他进程进行通信。


# 初始设置
CI系统通过检测代码存储库中的更改来运行测试，因此首先，我们需要设置 CI 系统将监控的存储库`test_repo`。
```bash
mkdir test_repo 
cd test_repo 
git init
```

`test_repo`是主存储库，开发人员进行修改的地方。我们的CI系统将从此存储库中进行拉取和检查，运行测试。

此外，我们还需要两个额外的存储库用于观察器和测试运行。
```bash
git clone /path/to/test_repo test_repo_clone_obs
git clone /path/to/test_repo test_repo_clone_runner
```

# 组件
## 观察者(repo_observer.py)

观察者用于监视存储库，发现新的提交时通知调度程序。
具体来说，观察者将定期轮询存储库，发现更改时，告诉调度程序需要进行测试的最新提交ID。

为了能通知调度程序，我们需要知道调度程序的地址和端口：
```python
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
```
观察者的主函数时poll()。此函数会执行无限循环，一直检查存储库的更改。
```python
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
```

>`update_repo.sh` 文件用于标识任何新的提交。由于笔者不熟悉bash语法，此处略过。原文有对该文件的具体说明。


当发现有新的提交，就通知调度程序：
```python
        # 有新的提交。通知调度(分发测试)。
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
```

## 调度程序(dispatcher.py)
调度程序用于委派测试任务。它侦听来自测试运行程序和观察者的请求。
- 测试程序可以在此注册自己。
- 观察者可以提交ID到这里。

当有待测试ID时，调度程序将分配给某个测试程序运行测试。

启动调度程序服务器和另外两个线程。一个线程运行 `runner_checker` 函数，另一个线程运行函数 `redistribute` 。
`runner_checker` 检查注册的测试运行程序的状态，确定它们有响应，否则将它们删除。
`redistribute` 检查待测试的提交`pending_commits`，并进行分配。
```python
def serve():
    args = parse_args()
    server = ThreadingTCPServer((args.host, int(args.port)), DispatcherHandler)
    print(f"serving on {args.host}:{int(args.port)}")  

    def runner_checker(server):
        '''通过ping 检查测试运行程序是否在线'''
        ...

    def redistribute(server):
        '''重新分配测试'''
        ...  

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
```


`dispatch_tests` 函数用于从已注册的运行器池中查找可用的测试运行器。如果可用，它将向其发送带有提交 ID 的运行测试消息。否则，等待两秒钟并重试。调度后，它会记录 dispatched_commits 变量中的哪个测试运行程序正在测试哪个提交 ID。如果提交 ID 在pending_commits 中，则会将其删除，因为 dispatch_tests 因为它已成功重新调度。

为了让调度程序服务器处理并发连接，`ThreadingTCPServer`使用 Mixin类，将线程处理功能添加到默认 SocketServer 
```python
class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
	...
```
调度程序服务器通过为每个请求定义处理程序来工作。这由`DispatcherHandler`类定义，该类继承自SocketServer的BaseRequestHandler。这个基类只需要我们定义`handle`函数，每当请求连接时就会调用它。

```python
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
        ...
```

## 测试运行程序(test_runner.py)
测试运行程序负责针对给定的提交 ID 运行测试并报告结果。它仅与调度程序服务器通信，该服务器负责为其提供要运行的提交 ID，并将接收测试结果。

`dispatcher_checker` 函数每 5 秒对调度程序服务器执行一次 ping 操作，以确保调度仍处于启动和运行状态。

测试运行程序也有一个`ThreadingTCPServer `，用来接收调度的消息。
测试运行程序服务器响应来自调度程序的两条消息。第一个是 ping ，调度程序服务器使用它来验证运行器是否仍处于活动状态。
```python
class TestHandler(SocketServer.BaseRequestHandler):
    ...
    def handle(self):
        ....
        if command == "ping":
            print("pinged")
            self.server.last_communication = time.time()
            self.request.sendall("pong")
```
第二个是 `runtest` ，它接受 形式的 `runtest:<commit ID>` 消息，并用于启动对给定提交的测试。调用 runtest 时，测试运行程序将检查它是否已在运行测试，如果是，它将向调度程序返回 BUSY 响应。如果可用，它将通过消息 OK。
```python
        elif command == "runtest":
            print("got runtest command: am I busy? %s" % self.server.busy)
            if self.server.busy:
                self.request.sendall("BUSY")
            else:
                self.request.sendall("OK")
                print("running")
                commit_id = command_groups.group(2)[1:]
                self.server.busy = True
                self.run_tests(commit_id,
                               self.server.repo_folder)
                self.server.busy = False
```


run_tests函数调用 shell 脚本 ，脚本test_runner_script.sh 将存储库更新为给定的提交 ID。脚本返回后，如果成功更新存储库，我们将使用 unittest 运行测试并将结果收集到文件中。测试完成运行后，测试运行程序将读取结果文件，并在结果消息中将其发送到调度程序。

# 流程图

![流程图](https://img-blog.csdnimg.cn/direct/a5ced51cb77e4fabb85b773bc977f9ee.png)
# 运行代码
我们可以在本地运行这个简单的 CI 系统，为每个进程使用三个不同的终端 shell。我们首先启动调度程序，在端口 8888 上运行：
```shell
python dispatcher.py
```
在一个新的 shell 中，我们启动测试运行程序：
```shell
python test_runner.py <path/to/test_repo_clone_runner>
```
最后，在另一个新 shell 中，让我们启动 repo 观察器：
```python
python repo_observer.py --dispatcher-server=localhost:8888 <path/to/repo_clone_obs>
```

现在一切都设置好了，让我们触发一些测试吧！为此，我们需要进行**新的提交**。转到主存储库并进行任意更改：
```shell
$ cd /path/to/test_repo
$ touch new_file
$ git add new_file
$ git commit -m"new file" new_file
```

然后 repo_observer.py 会意识到有一个新的提交并通知调度程序。您可以在它们各自的 shell 中看到输出，以便监视它们。调度程序收到测试结果后，会使用提交 ID 作为文件名，将它们存储在此代码库的 test_results/ 文件夹中。

![在这里插入图片描述](https://img-blog.csdnimg.cn/direct/0ad08d5d4f1f44f5b1f90d8c40531f77.png)

# 错误处理
此 CI 系统包括一些简单的错误处理。
如果终止进程 test_runner.py ， dispatcher.py 则会发现运行器不再可用，并将其从池中删除。

您还可以终止测试运行程序，以模拟计算机崩溃或网络故障。如果这样做，调度程序将意识到运行器已关闭，并将向另一个测试运行程序（如果池中有一个可用）提供作业，或者将等待新的测试运行程序在池中注册自己。

如果你杀死了调度程序，存储库观察者会发现它已经关闭，并会抛出一个异常。测试运行器也会注意到并关闭。

# 结论
通过关注点分离，我们构建了分布式CI系统。通过套接字通信，我们能将系统分布在多个机器上，增加了系统的可扩展性。

 CI 系统现在非常简单，您可以自己扩展它以使其功能更强大。以下是一些改进建议：
 - 每次提交测试运行：当前系统将定期检查是否运行了新提交，并将运行最近的提交。这应该得到改进，以测试每个提交。为此，您可以修改定期检查程序，以在上次测试和最新提交之间的日志中调度每个提交的测试运行。
 - 更智能的测试运行程序：如果测试运行程序检测到调度程序无响应，它将停止运行。即使测试运行程序正在运行测试，也会发生这种情况！如果测试运行程序等待一段时间（或者无限期，如果您不关心资源管理），以便调度程序重新联机，那就更好了。在这种情况下，如果调度程序在测试运行程序主动运行测试时关闭，则它不会关闭，而是完成测试并等待调度程序重新联机，并将结果报告给它。这将确保我们不会浪费测试运行者所做的任何努力，并且我们每次提交只会运行一次测试。
 -  真实报告：在实际的 CI 系统中，您将将测试结果报告给报告服务，该服务将收集结果，将它们发布到某个地方供人们查看，并在发生故障或其他显着事件时通知相关方列表。您可以通过创建一个新流程来获取报告的结果，而不是由调度程序收集结果来扩展我们的简单 CI 系统。这个新过程可以是一个 Web 服务器（或者可以连接到 Web 服务器），它可以在线发布结果，并且可以使用邮件服务器来提醒订阅者任何测试失败。
 - 测试运行程序管理器：现在，您必须手动启动 test_runner.py 该文件才能启动测试运行程序。相反，您可以创建一个测试运行程序管理器进程，该进程将评估来自调度程序的测试请求的当前负载，并相应地缩放活动测试运行程序的数量。此进程将接收运行测试消息，并将为每个请求启动测试运行程序进程，并在负载减少时终止未使用的进程。


