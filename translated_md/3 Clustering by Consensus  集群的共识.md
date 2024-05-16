# 介绍
在本章中，我们将探讨支持分布式计算的网络协议的实现。

## 动机
本文的重点是协议实现，但作为动机，让我们考虑一个银行**账户管理**服务。在此服务中，每个账户有一个余额，用户可以进行**存款**、**转账**、**获取余额**等操作。**转账**操作需要同时在两个账户上进行——源账户和目标账户——如果源账户余额过低，则拒绝该操作。
如果服务在单个服务器上运行，则很容易实现：使用**锁**确保操作执行顺序。但是，单个服务器很难处理大量的请求，因此，需要在多个服务器上运行服务。在分布式处理的朴素实现中，每个服务器都会保留每个帐户余额的本地副本。它将处理收到的任何操作，并将帐户余额的更新发送到其他服务器。该方法在一个严重的问题：如果两台服务器同时处理同一账户的操作，那么哪个新账户余额是正确的？即使服务器彼此共享操作而不是余额，同时从帐户中转出两次也可能会透支帐户。因此，我们需要确定本地状态和其他服务器上的状态匹配。

从根本上讲，当服务器使用其本地状态执行操作，而不先确保本地状态与其他服务器上的状态匹配时，这些故障就会发生。例如，假设服务器 A 收到了从账户 101 转账至账户 202 的转账操作，而服务器 B 已经处理了另一笔从账户 101 的全部余额转至账户 202 的转账，但尚未通知服务器 A。服务器 A 上的本地状态与服务器 B 上的不同，因此服务器 A 错误地允许转账完成，即使结果是账户 101 透支。
## 分布式状态机
避免此类问题的技术称为“**分布式状态机**”。这个想法是每个服务器在完全相同的输入上执行完全相同的确定性状态机。因此，根据状态机的性质，每个服务器将看到完全相同的输出。诸如“transfer”或“get-balance”之类的操作及其参数（帐号和金额）表示状态机的输入。

此应用程序的状态机很简单：
```python
 	def execute_operation(state, operation):
        if operation.name == 'deposit':
            if not verify_signature(operation.deposit_signature):
                return state, False
            state.accounts[operation.destination_account] += operation.amount
            return state, True
        elif operation.name == 'transfer':
            if state.accounts[operation.source_account] < operation.amount:
                return state, False
            state.accounts[operation.source_account] -= operation.amount
            state.accounts[operation.destination_account] += operation.amount
            return state, True
        elif operation.name == 'get-balance':
            return state, state.accounts[operation.account]
```

请注意，执行“get-balance”操作不会修改状态，但仍作为状态转换实现。这保证了返回的余额是服务器集群中的最新信息，而不是基于单个服务器上的（可能已过时的）本地状态。

因此，分布式状态机技术可确保在每个主机上**执行相同的操作**。但问题仍然存在，如何确保每个服务器都有**一致的**状态机的输入。这是一个**共识**(consensus)问题，我们将用 **Paxos** 算法的一个派生版本来解决它。
## Consensus by Paxos
Paxos 的最简单形式为一组服务器就某个值在所有时间上达成一致提供了一种方式。Multi-Paxos 是在此基础上构建，通过逐个达成一系列编号的事实。为了实现分布式状态机，我们使用 Multi-Paxos 就每个状态机输入达成一致，并按顺序执行它们。

>译者注：Poxos比较难理解，可以结合例子或其他资料理解。
>[B站视频](https://www.bilibili.com/video/BV1kA411G7cK)

### Simple Paxos
让我们从“Simple Paxos”开始，也称为 Synod（主教会议） 协议，它提供了一种就永不改变的单一值达成一致的方法。**Paxos**这个名字来自“兼职议会”中的神话岛屿，立法者通过主教会议的过程对立法进行**投票**。

在此示例中，我们要确定的单个值是银行处理的**第一笔交易**。虽然银行每天都会处理交易，但第一笔交易只会发生一次，永远不会改变，因此我们可以使用 Simple Paxos 达成一致。

该协议在一系列**投票**中运作，每轮投票由集群中的一个**提议者**(proposer)领导。每个投票都有一个基于整数和提议者身份的唯一选票**编号**。提议者的目标是让大多数集群成员（即**接受者**(acceptor)）接受其提议的值（除非已经有了一个值）。
![图3.1 投票](https://img-blog.csdnimg.cn/direct/fe3c077400d44752bceadfd75de1e357.png)
投票过程如图3.1 所示：
**Prepara阶段：**
投票开始时，**提议者**向多个**接收者**发送带有选票编号N的`Prepara(N)`信息，并等待多数人的回复。`Prepare` 请求小于 N 的最高选票编号的**已接受值**（如果有）。接受者回复他们已经接受的值，并承诺将来不接受任何编号小于 N 的投票。如果接受者已经对更大的选票编号做出了承诺，它会将该编号包含在 `Promise` 中，表明提议者已被抢占。在这种情况下，本轮投票已经结束，但提议者可以自由地在另一张（编号更大的）选票中再次尝试。
 **accpet阶段：**
当提议者收到**大多数接受者**的回复后，它会向所有接受者发送一条 `Accept(N,val) `信息，包括选票编号和值。如果提议者没有从任何接受者那里收到任何现有值，那么它就会发送自己的期望值。否则，它会发送具有**最高编号的`Promise`中的值**。除非违背了承诺，否则每个接受者都将`Accept`消息中的值记录为已接受，并回复`Accepted(N)`消息。当提议者**从大多数接受者**那里收到了自己的投票编号时，**投票完成并且值被决定**。

回到示例，最初没有其他值被接受，所以接受者们发回一个没有值的`Promise` ，提议者A发送一个包含自己期望值的`Accept` ，比如：
```
 operation(name='deposit', amount=100.00, destination_account='Mike DiBernardo')
```

如果另一位提议者B后来以**较低**的选票编号和不同的操作（例如，transfer to  'Dustin J. Mitchell' ）发起投票，接受者会直接拒绝。但是如果该选票的选票**编号较大**，则 接受者将通过`Promise` 通知提议者B之前的值(deposit 100 to Mike)，并在Accept中发送之前的值，达成与第一轮投票相同的值。

事实上，即使选票重叠、消息延迟或少数接受者失败，该协议也永远不会允许两个不同的值被决定。
当多个提议者同时进行选票时，很容易导致两个选票都不被接受。然后两个提议者重新提议，希望其中一个胜出，但如果时机恰到好处（恰倒坏处），**僵局可能会无限期地持续下去**。
请考虑这样的情况：
- 提议者A执行1号投票的Prepare/Promise 阶段
- 在提议者A完成投票（被接受）前，提议者B对2号投票执行了Prepare/Promise阶段
- 当提议者A最终Accept1号投票时，接收者拒绝了1号投票，因为它们已经承诺了2号投票。
- 提议者A立刻发送号码更高的3号投票，提议者B发送 Accept 2号投票的消息。
- 类似的，提议者B的后续Accept被拒绝（因为接收者已经承诺了3号投票）。


### Multi-Paxos 
在**单个静态值**上达成共识本身并不特别有用。像银行账户服务这样的集群系统希望就随**时间变化的特定状态**（账户余额）达成一致。我们使用 Paxos 协议来就每个操作达成一致，将其视为状态机转换。

Multi-Paxos实际上是一系列简单的Paxos实例（插槽,slot），每个都按顺序编号。每个状态转换被赋予一个“插槽编号”，集群中的每个成员按严格的数字顺序执行转换。要更改集群的状态（例如处理转账操作），我们尝试在下一个插槽上就该操作达成共识。具体来说，这意味着将插槽编号添加到每个消息中，所有协议状态都按插槽进行跟踪。

为每个插槽都运行 Paxos，至少需要两轮往返，太慢了。Multi-Paxos 通过为所有插槽使用相同的选票号码，并同时执行所有插槽的`Prpare`/`Promise`阶段来进行优化。

### Paxos不实用（略）
在实用软件中实现 Multi-Paxos 是出了名的困难，催生了许多论文嘲笑 Lamport 的“Paxos Made Simple”，标题为“Paxos Made Practical”。
...

# 集群简介
本章中的 Cluster 库实现了一种简单形式的 Multi-Paxos。它被设计为一个库，为更大的应用程序提供共识(consensus)服务。

这个库的用户将依赖于它的正确性，因此重要的是结构化代码，以便我们可以阅读—— 并测试 —— 它与规范的对应关系。复杂的协议可能会表现出复杂的失败，因此我们将构建支持以重现和调试罕见失败的功能。

本章中的实现是概念验证代码：足以证明核心概念是实用的，但没有用于在生产环境中使用所需的所有普通设备。代码的结构使得稍后可以通过对核心实现进行最小的更改来添加这些设备。

让我们开始吧。
## 类型和常量
Cluster 的协议使用 15 种不同的消息类型，通过**命名元组（namedtuple）** 实现。
```python
    Accepted = namedtuple('Accepted', ['slot', 'ballot_num'])
    Accept = namedtuple('Accept', ['slot', 'ballot_num', 'proposal'])
    Decision = namedtuple('Decision', ['slot', 'proposal'])
    Invoked = namedtuple('Invoked', ['client_id', 'output'])
    Invoke = namedtuple('Invoke', ['caller', 'client_id', 'input_value'])
    Join = namedtuple('Join', [])
    Active = namedtuple('Active', [])
    Prepare = namedtuple('Prepare', ['ballot_num'])
    Promise = namedtuple('Promise', ['ballot_num', 'accepted_proposals'])
    Propose = namedtuple('Propose', ['slot', 'proposal'])
    Welcome = namedtuple('Welcome', ['state', 'slot', 'decisions'])
    Decided = namedtuple('Decided', ['slot'])
    Preempted = namedtuple('Preempted', ['slot', 'preempted_by'])
    Adopted = namedtuple('Adopted', ['ballot_num', 'accepted_proposals'])
    Accepting = namedtuple('Accepting', ['leader'])
```

使用命名元组来描述每种消息类型可以保持代码干净，并有助于避免一些简单的错误。命名的元组构造函数如果没有被赋予完全正确的属性，就会引发异常，使拼写错误变得明显。元组在日志消息中很好地设置了自己的格式，并且作为额外的奖励，不会像字典那样使用那么多的内存。

创建消息：
```python
msg = Accepted(slot=10, ballot_num=30)
```
访问字段：
```python
got_ballot_num = msg.ballot_num
```

该代码还引入了一些常量，其中大多数常量定义了各种消息的超时：
```python
    JOIN_RETRANSMIT = 0.7
    CATCHUP_INTERVAL = 0.6
    ACCEPT_RETRANSMIT = 1.0
    PREPARE_RETRANSMIT = 1.0
    INVOKE_RETRANSMIT = 0.5
    LEADER_TIMEOUT = 1.0
    NULL_BALLOT = Ballot(-1, -1)  # sorts before all real ballots
    NOOP_PROPOSAL = Proposal(None, None, None)  # no-op to fill otherwise empty slots
```
最后，Cluster 使用**namedtuple**实现协议描述的两种数据类型：
```python
    Proposal = namedtuple('Proposal', ['caller', 'client_id', 'input'])
    Ballot = namedtuple('Ballot', ['n', 'leader'])
```

## 组件模型
为了保持可测试性和可读性，我们将Cluster分解为协议中描述的**角色**对应的几个类，每个类都是`Role`的子类。
```python
class Role(object):
    def __init__(self, node):
        self.node = node
        self.node.register(self)
        self.running = True
        self.logger = node.logger.getChild(type(self).__name__)
    def set_timer(self, seconds, callback):
        return self.node.network.set_timer(self.node.address, seconds,
                                           lambda: self.running and callback())
    def stop(self):
        self.running = False
        self.node.unregister(self)
```

一个集群节点所拥有的角色由 `Node` 类粘合在一起，该类表示**网络上的单个节点**。随着执行的进行，**角色在节点中添加或删除**。到达节点的消息将转发到所有活动的角色，调用 `do_` 前缀的消息类型方法。这些 `do_ `方法通过关键字参数接收将消息的属性，以便于访问。 `Node` 类还提供了一个 `send` 方法，使用`functools.partial` 为 `Network `类的`send`方法提供一些参数。
```python
class Node(object):
    unique_ids = itertools.count()
    def __init__(self, network, address):
        self.network = network
        self.address = address or 'N%d' % self.unique_ids.next()
        self.logger = SimTimeLogger(
            logging.getLogger(self.address), {'network': self.network})
        self.logger.info('starting')
        self.roles = []
        self.send = functools.partial(self.network.send, self)
    def register(self, roles):
        self.roles.append(roles)
    def unregister(self, roles):
        self.roles.remove(roles)
    def receive(self, sender, message):
        handler_name = 'do_%s' % type(message).__name__
        for comp in self.roles[:]:
            if not hasattr(comp, handler_name):
                continue
            comp.logger.debug("received %s from %s", message, sender)
            fn = getattr(comp, handler_name)
            fn(sender=sender, **message._asdict())
```

## 应用接口
应用程序在每个集群成员上创建并启动一个 `Member `对象，提供特定于应用程序的**状态机**和对等列表。如果节点要加入现有集群，则member会向节点添加引导角色(bootstrap)，如果要创建新集群，则会向节点添加种子。然后，它在单独的线程中运行协议（通过 `Network.run` ）。

应用程序通过`invoke` 方法与Cluster交互，该方法启动了状态转换提议(proposel)。一旦决定了该提议并运行状态机，`invoke` 就会返回机器的输出，该方法使用简单的同步队列 `Queue` 来等待来自协议线程的结果。
```python
class Member(object):
    def __init__(self, state_machine, network, peers, seed=None,
                 seed_cls=Seed, bootstrap_cls=Bootstrap):
        self.network = network
        self.node = network.new_node()
        if seed is not None:
            self.startup_role = seed_cls(self.node, initial_state=seed, peers=peers,
                                      execute_fn=state_machine)
        else:
            self.startup_role = bootstrap_cls(self.node,
                                      execute_fn=state_machine, peers=peers)
        self.requester = None
    def start(self):
        self.startup_role.start()
        self.thread = threading.Thread(target=self.network.run)
        self.thread.start()
    def invoke(self, input_value, request_cls=Requester):
        assert self.requester is None
        q = Queue.Queue()
        self.requester = request_cls(self.node, input_value, q.put)
        self.requester.start()
        output = q.get()
        self.requester = None
        return output
```
## Role Classes
让我们逐一查看每个角色类。

### Acceptor  接受者
`Acceptor` 在协议中实现**接受者**角色，因此它必须存储代表其最新承诺的**选票编号**，以及每个插槽的**一组已接受提案**。然后，它根据协议响应 `Prepare` 和 `Accept` 发送消息。
对于接受者来说，Multi-Paxos和Simple Paxos类似，只是在消息中添加了插槽编号。

```python
class Acceptor(Role):
    def __init__(self, node):
        super(Acceptor, self).__init__(node)
        self.ballot_num = NULL_BALLOT
        self.accepted_proposals = {}  # {slot: (ballot_num, proposal)}
    def do_Prepare(self, sender, ballot_num):
        if ballot_num > self.ballot_num:
            self.ballot_num = ballot_num
            # we've heard from a scout, so it might be the next leader
            self.node.send([self.node.address], Accepting(leader=sender))
        self.node.send([sender], Promise(
            ballot_num=self.ballot_num, 
            accepted_proposals=self.accepted_proposals
        ))
    def do_Accept(self, sender, ballot_num, slot, proposal):
        if ballot_num >= self.ballot_num:
            self.ballot_num = ballot_num
            acc = self.accepted_proposals
            if slot not in acc or acc[slot][0] < ballot_num:
                acc[slot] = (ballot_num, proposal)
        self.node.send([sender], Accepted(
            slot=slot, ballot_num=self.ballot_num))
```

### Replica （副本）
`Replica`类是本程序中最复杂的角色类，因为它有以下职责：
- 提出新的提议
- 在决定提案时调用本地状态机器
- 跟踪当前领导者
- 将新启动的节点添加到集群

副本根据来自客户端的 `Invoke`消息创建新的提案，选择未使用的插槽并向当前领导者发送 `Propose`消息 。此外，如果所选插槽的共识是针对不同的提案，则副本必须使用新插槽重新提案。
![在这里插入图片描述](https://img-blog.csdnimg.cn/direct/cb41d955d00e4ead8f4a078bbfca3889.png)

`Decision` 消息表示集群已达成共识的插槽。在这里，副本存储新的决策，然后运行状态机，直到它到达未决定的插槽。副本将集群已同意的决定插槽与本地状态机已处理的已提交插槽区分开来。当时段被无序决定时，提交的提案可能会滞后，等待下一个时段被决定。提交插槽时，每个副本都会向请求者发送一条包含操作结果的`Invoked` 消息。

在某些情况下，插槽可能没有有效的提案和决定。状态机需要逐个执行插槽，因此集群必须就填充插槽的内容达成共识。为了防止这种可能性，副本在赶上插槽时会提出“不操作”建议。如果最终决定了这样的提议，那么状态机不会对该插槽执行任何操作。

同样，同一提案也有可能被决定两次。副本会跳过对任何此类重复建议的状态机调用，不对该插槽执行任何转换。

副本需要知道哪个节点是活动的领导者，以便向其发送 Propose 消息。要做到这一点，需要大量技巧，我们稍后将看到。每个副本使用三个信息源跟踪活动的领导者。
当领导者角色变为活动状态时，它会向同一节点上的副本发送一条 `Adopted `消息（图 3.3）。
![3.3](https://img-blog.csdnimg.cn/direct/f4adf1e1b14443d99cef31afcf655f58.png)
当接受器向新的领导者发送`Promise` 时，它会向其本地副本发送一条 `Accepting` 消息。
![3.4](https://img-blog.csdnimg.cn/direct/5762983ee03c45dea05a4067069f9bed.png)
活动领导者以心跳的形式发送 `Active` 消息（图 3.5。如果在 LEADER_TIMEOUT 过期之前没有收到此类消息，则副本将假定领导者已死亡，并移动到下一个领导者。在这种情况下，所有副本都必须选择相同的新领导者，我们通过对成员进行排序并选择列表中的下一个成员来实现这一点。
![3.5](https://img-blog.csdnimg.cn/direct/e642dfc41a5741edaa91034c3a4e8151.png)

最后，当节点加入网络时，引导角色会发送一条 `Join` 消息（图 3.6）。副本会以包含其最新状态 `Welcome` 的消息进行响应，从而使新节点能够快速启动。
![3.6](https://img-blog.csdnimg.cn/direct/06237f1fc02a422e817650f772eb1807.png)

```python
class Replica(Role):

    def __init__(self, node, execute_fn, state, slot, decisions, peers):
        super(Replica, self).__init__(node)
        self.execute_fn = execute_fn
        self.state = state
        self.slot = slot
        self.decisions = decisions
        self.peers = peers
        self.proposals = {}
        # next slot num for a proposal (may lead slot)
        self.next_slot = slot
        self.latest_leader = None
        self.latest_leader_timeout = None

    # making proposals

    def do_Invoke(self, sender, caller, client_id, input_value):
        proposal = Proposal(caller, client_id, input_value)
        slot = next((s for s, p in self.proposals.iteritems() if p == proposal), None)
        # propose, or re-propose if this proposal already has a slot
        self.propose(proposal, slot)

    def propose(self, proposal, slot=None):
        """Send (or resend, if slot is specified) a proposal to the leader"""
        if not slot:
            slot, self.next_slot = self.next_slot, self.next_slot + 1
        self.proposals[slot] = proposal
        # find a leader we think is working - either the latest we know of, or
        # ourselves (which may trigger a scout to make us the leader)
        leader = self.latest_leader or self.node.address
        self.logger.info(
            "proposing %s at slot %d to leader %s" % (proposal, slot, leader))
        self.node.send([leader], Propose(slot=slot, proposal=proposal))

    # handling decided proposals

    def do_Decision(self, sender, slot, proposal):
        assert not self.decisions.get(self.slot, None), \
                "next slot to commit is already decided"
        if slot in self.decisions:
            assert self.decisions[slot] == proposal, \
                "slot %d already decided with %r!" % (slot, self.decisions[slot])
            return
        self.decisions[slot] = proposal
        self.next_slot = max(self.next_slot, slot + 1)

        # re-propose our proposal in a new slot if it lost its slot and wasn't a no-op
        our_proposal = self.proposals.get(slot)
        if (our_proposal is not None and 
            our_proposal != proposal and our_proposal.caller):
            self.propose(our_proposal)

        # execute any pending, decided proposals
        while True:
            commit_proposal = self.decisions.get(self.slot)
            if not commit_proposal:
                break  # not decided yet
            commit_slot, self.slot = self.slot, self.slot + 1

            self.commit(commit_slot, commit_proposal)

    def commit(self, slot, proposal):
        """Actually commit a proposal that is decided and in sequence"""
        decided_proposals = [p for s, p in self.decisions.iteritems() if s < slot]
        if proposal in decided_proposals:
            self.logger.info(
                "not committing duplicate proposal %r, slot %d", proposal, slot)
            return  # duplicate

        self.logger.info("committing %r at slot %d" % (proposal, slot))
        if proposal.caller is not None:
            # perform a client operation
            self.state, output = self.execute_fn(self.state, proposal.input)
            self.node.send([proposal.caller], 
                Invoked(client_id=proposal.client_id, output=output))

    # tracking the leader

    def do_Adopted(self, sender, ballot_num, accepted_proposals):
        self.latest_leader = self.node.address
        self.leader_alive()

    def do_Accepting(self, sender, leader):
        self.latest_leader = leader
        self.leader_alive()

    def do_Active(self, sender):
        if sender != self.latest_leader:
            return
        self.leader_alive()

    def leader_alive(self):
        if self.latest_leader_timeout:
            self.latest_leader_timeout.cancel()

        def reset_leader():
            idx = self.peers.index(self.latest_leader)
            self.latest_leader = self.peers[(idx + 1) % len(self.peers)]
            self.logger.debug("leader timed out; tring the next one, %s", 
                self.latest_leader)
        self.latest_leader_timeout = self.set_timer(LEADER_TIMEOUT, reset_leader)

    # adding new cluster members

    def do_Join(self, sender):
        if sender in self.peers:
            self.node.send([sender], Welcome(
                state=self.state, slot=self.slot, decisions=self.decisions))
```

### Leader, Scout, and Commander

**领导者**（Leader）的主要任务是接收 Propose 请求新选票的信息并做出决定。当领导者成功执行协议的 Prepare  / Promise 部分时，它是“活跃的”。活跃的领导者可以立即发送 Accept 消息以响应 Propose 。

为了与每个角色的类模型保持一致，领导者委派**侦察员**（Scout）**和指挥官**（Commander）来执行协议的每个部分。
```python
class Leader(Role):

    def __init__(self, node, peers, commander_cls=Commander, scout_cls=Scout):
        super(Leader, self).__init__(node)
        self.ballot_num = Ballot(0, node.address)
        self.active = False
        self.proposals = {}
        self.commander_cls = commander_cls
        self.scout_cls = scout_cls
        self.scouting = False
        self.peers = peers

    def start(self):
        # reminder others we're active before LEADER_TIMEOUT expires
        def active():
            if self.active:
                self.node.send(self.peers, Active())
            self.set_timer(LEADER_TIMEOUT / 2.0, active)
        active()

    def spawn_scout(self):
        assert not self.scouting
        self.scouting = True
        self.scout_cls(self.node, self.ballot_num, self.peers).start()

    def do_Adopted(self, sender, ballot_num, accepted_proposals):
        self.scouting = False
        self.proposals.update(accepted_proposals)
        # note that we don't re-spawn commanders here; if there are undecided
        # proposals, the replicas will re-propose
        self.logger.info("leader becoming active")
        self.active = True

    def spawn_commander(self, ballot_num, slot):
        proposal = self.proposals[slot]
        self.commander_cls(self.node, ballot_num, slot, proposal, self.peers).start()

    def do_Preempted(self, sender, slot, preempted_by):
        if not slot:  # from the scout
            self.scouting = False
        self.logger.info("leader preempted by %s", preempted_by.leader)
        self.active = False
        self.ballot_num = Ballot((preempted_by or self.ballot_num).n + 1, 
                                 self.ballot_num.leader)

    def do_Propose(self, sender, slot, proposal):
        if slot not in self.proposals:
            if self.active:
                self.proposals[slot] = proposal
                self.logger.info("spawning commander for slot %d" % (slot,))
                self.spawn_commander(self.ballot_num, slot)
            else:
                if not self.scouting:
                    self.logger.info("got PROPOSE when not active - scouting")
                    self.spawn_scout()
                else:
                    self.logger.info("got PROPOSE while scouting; ignored")
        else:
            self.logger.info("got PROPOSE for a slot already being proposed")
```


领导者想要变为活跃时，就会创建一个侦察者角色，以回应在其不活跃时收到的 `Propose`（图 3.7）。Scout发送（并在必要时重新发送）一条 `Prepare` 消息，并收集 `Promise` 响应，直到它从大多数同行那里听到或被抢占。它分别用 Adopted 或 Preempted 与领导者通信。

![3.7](https://img-blog.csdnimg.cn/direct/6fccde9d6d4c455ba40b8507055cd9ed.png)

```python
class Scout(Role):

    def __init__(self, node, ballot_num, peers):
        super(Scout, self).__init__(node)
        self.ballot_num = ballot_num
        self.accepted_proposals = {}
        self.acceptors = set([])
        self.peers = peers
        self.quorum = len(peers) / 2 + 1
        self.retransmit_timer = None

    def start(self):
        self.logger.info("scout starting")
        self.send_prepare()

    def send_prepare(self):
        self.node.send(self.peers, Prepare(ballot_num=self.ballot_num))
        self.retransmit_timer = self.set_timer(PREPARE_RETRANSMIT, self.send_prepare)

    def update_accepted(self, accepted_proposals):
        acc = self.accepted_proposals
        for slot, (ballot_num, proposal) in accepted_proposals.iteritems():
            if slot not in acc or acc[slot][0] < ballot_num:
                acc[slot] = (ballot_num, proposal)

    def do_Promise(self, sender, ballot_num, accepted_proposals):
        if ballot_num == self.ballot_num:
            self.logger.info("got matching promise; need %d" % self.quorum)
            self.update_accepted(accepted_proposals)
            self.acceptors.add(sender)
            if len(self.acceptors) >= self.quorum:
                # strip the ballot numbers from self.accepted_proposals, now that it
                # represents a majority
                accepted_proposals = \ 
                    dict((s, p) for s, (b, p) in self.accepted_proposals.iteritems())
                # We're adopted; note that this does *not* mean that no other
                # leader is active.  # Any such conflicts will be handled by the
                # commanders.
                self.node.send([self.node.address],
                    Adopted(ballot_num=ballot_num, 
                            accepted_proposals=accepted_proposals))
                self.stop()
        else:
            # this acceptor has promised another leader a higher ballot number,
            # so we've lost
            self.node.send([self.node.address], 
                Preempted(slot=None, preempted_by=ballot_num))
            self.stop()
```

领导者为每个具有活动提案的插槽创建一个**指挥官**(Commander)角色（图 3.8）。像侦察兵一样，指挥官发送和重新发送 `Accept` 消息，并等待大多数接受者回复 `Accepted` ，或等待其抢占的消息。当提案被接受时，指挥官会向所有节点广播消息`Decision` 。它用 `Decided` 或 `Preempted` （抢占）响应领导者。
![3.8](https://img-blog.csdnimg.cn/direct/25835fd78b8f40138f960995c6b9dd09.png)


```python
class Commander(Role):
    def __init__(self, node, ballot_num, slot, proposal, peers):
        super(Commander, self).__init__(node)
        self.ballot_num = ballot_num
        self.slot = slot
        self.proposal = proposal
        self.acceptors = set([])
        self.peers = peers
        self.quorum = len(peers) / 2 + 1
    def start(self):
        self.node.send(set(self.peers) - self.acceptors, Accept(
            slot=self.slot, ballot_num=self.ballot_num, proposal=self.proposal))
        self.set_timer(ACCEPT_RETRANSMIT, self.start)
    def finished(self, ballot_num, preempted):
        if preempted:
            self.node.send([self.node.address], 
                           Preempted(slot=self.slot, preempted_by=ballot_num))
        else:
            self.node.send([self.node.address], 
                           Decided(slot=self.slot))
        self.stop()
    def do_Accepted(self, sender, slot, ballot_num):
        if slot != self.slot:
            return
        if ballot_num == self.ballot_num:
            self.acceptors.add(sender)
            if len(self.acceptors) < self.quorum:
                return
            self.node.send(self.peers, Decision(
                           slot=self.slot, proposal=self.proposal))
            self.finished(ballot_num, False)
        else:
            self.finished(ballot_num, True)
```

>作为一个旁白，在开发过程中出现了一个令人惊讶的微妙错误。当时，网络模拟器甚至在一个节点内的消息上引入了丢包。当所有 Decision 消息丢失时，协议无法继续。副本继续重新传输 Propose 消息，但领导者将其忽略，因为它已经给出了该时刻的提案。副本的追赶过程找不到结果，因为没有副本听说过这个决定。解决方案是确保本地消息始终能够传递，就像真实网络堆栈一样。

### Bootstrap
当一个节点加入集群时，它必须在参与之前确定当前的集群状态。引导角色（Bootstrap）通过依次向每个对等节点发送加入消息（`Join`）来处理此事，直到它收到欢迎消息（`Welcome`）。引导角色的通信图在副本（Replica）中显示。
该实现的早期版本使用一整套角色（副本、领导者和接受者）启动每个节点，每个角色都从“启动”阶段开始，等待`Welcome`消息中的信息。这会将初始化逻辑分散到每个角色周围，需要对每个角色进行单独的测试。最终设计具有引导角色，在启动完成后将其他每个角色添加到节点，并将初始状态传递给它们的构造函数。
```python
class Bootstrap(Role):
    def __init__(self, node, peers, execute_fn,
                 replica_cls=Replica, acceptor_cls=Acceptor, leader_cls=Leader,
                 commander_cls=Commander, scout_cls=Scout):
        super(Bootstrap, self).__init__(node)
        self.execute_fn = execute_fn
        self.peers = peers
        self.peers_cycle = itertools.cycle(peers)
        self.replica_cls = replica_cls
        self.acceptor_cls = acceptor_cls
        self.leader_cls = leader_cls
        self.commander_cls = commander_cls
        self.scout_cls = scout_cls
    def start(self):
        self.join()
    def join(self):
        self.node.send([next(self.peers_cycle)], Join())
        self.set_timer(JOIN_RETRANSMIT, self.join)
    def do_Welcome(self, sender, state, slot, decisions):
        self.acceptor_cls(self.node)
        self.replica_cls(self.node, execute_fn=self.execute_fn, peers=self.peers,
                         state=state, slot=slot, decisions=decisions)
        self.leader_cls(self.node, peers=self.peers, commander_cls=self.commander_cls,
                        scout_cls=self.scout_cls).start()
        self.stop()
```

### Seed
在正常操作中，当节点加入集群时，它希望找到已经在运行的集群，至少有一个节点愿意响应 `Join` 消息。但是集群是如何启动呢？一种选择是引导角色在尝试联系其他每个节点后确定它是集群中的第一个节点。但这有两个问题。首先，对于大型集群来说，这意味着每次 `Join` 超时都需要等待很长时间。更重要的是，在发生网络分区的情况下，新节点可能无法联系任何其他节点并启动新集群。

网络**分区**是群集应用程序最具挑战性的故障案例。在网络分区中，所有集群成员都保持活动状态，但某些成员之间的通信失败。例如，如果加入具有柏林和台北节点的集群的网络链路失败，则网络将被分区。如果群集的两个部分在分区期间继续运行，则在网络链路恢复后重新联接这些部分可能具有挑战性。在 Multi-Paxos 的情况下，修复后的网络将托管两个集群，对相同的插槽编号做出不同的决策。

为避免这种结果，创建一个新的集群是用户指定的操作。集群中只有一个节点运行种子角色，其他节点像往常一样运行引导程序。种子节点等待直到它从大多数同行那里收到 `Join` 条消息，然后发送一个 `Welcome` ，其中包含状态机的初始状态和一组空决策。种子角色然后停止自己并启动引导角色以加入新种子集群。

Seed 模拟引导程序/副本交互的 `Join` / `Welcome` 部分，因此其通信图与副本角色的通信图相同。

```python
class Seed(Role):
    def __init__(self, node, initial_state, execute_fn, peers, 
                 bootstrap_cls=Bootstrap):
        super(Seed, self).__init__(node)
        self.initial_state = initial_state
        self.execute_fn = execute_fn
        self.peers = peers
        self.bootstrap_cls = bootstrap_cls
        self.seen_peers = set([])
        self.exit_timer = None
    def do_Join(self, sender):
        self.seen_peers.add(sender)
        if len(self.seen_peers) <= len(self.peers) / 2:
            return
        # cluster is ready - welcome everyone
        self.node.send(list(self.seen_peers), Welcome(
            state=self.initial_state, slot=1, decisions={}))
        # stick around for long enough that we don't hear any new JOINs from
        # the newly formed cluster
        if self.exit_timer:
            self.exit_timer.cancel()
        self.exit_timer = self.set_timer(JOIN_RETRANSMIT * 2, self.finish)
    def finish(self):
        # bootstrap this node into the cluster we just seeded
        bs = self.bootstrap_cls(self.node, 
                                peers=self.peers, execute_fn=self.execute_fn)
        bs.start()
        self.stop()
```

### Requester 
请求者角色管理对分布式状态机的请求。Requester类只是将 `Invoke`消息 发送到本地副本，直到它收到相应的 `Invoked` 。请参阅上面的“副本”部分，了解此角色的通信图。
```python
class Requester(Role):
    client_ids = itertools.count(start=100000)
    def __init__(self, node, n, callback):
        super(Requester, self).__init__(node)
        self.client_id = self.client_ids.next()
        self.n = n
        self.output = None
        self.callback = callback
    def start(self):
        self.node.send([self.node.address], 
                       Invoke(caller=self.node.address, 
                              client_id=self.client_id, input_value=self.n))
        self.invoke_timer = self.set_timer(INVOKE_RETRANSMIT, self.start)
    def do_Invoked(self, sender, client_id, output):
        if client_id != self.client_id:
            return
        self.logger.debug("received output %r" % (output,))
        self.invoke_timer.cancel()
        self.callback(output)
        self.stop()
```

### Summary
总而言之，集群的角色有：
- Acceptor（接受者）：做出承诺并接受建议
- Repplica（副本）：管理分布式状态机：提交提案、提交决策和响应请求者
-  Leader（领导者）： 领导Multi-Paxos算法的轮次
- Scout（侦察）： 为领导者执行 Multi-Paxos 算法 Prepare 的 / Promise 部分
- Commander（指挥官）：为领导者执行 Multi-Paxos 算法的 Accept / Accepted 部分
- Bootstrap（启动）： 将新节点引入现有集群
- Seed（种子）：创建新集群
-  Requester（请求）：请求分布式状态机操作


要使 Cluster 运行，只需要另外一种设备：所有节点通过**网络**进行通信。
## Network 网络
任何网络协议都需要能够**发送**和**接收**消息，以及在未来某个时间**调用**函数的方法。

`Network` 类提供了具有这些功能的简单模拟网络，还模拟了数据包**丢失**和消息传播**延迟**。

计时器（Timers）使用 `heapq` 的模块进行处理，从而可以有效地选择下一个事件。设置计时器涉及将 Timer 对象推到堆上。由于从堆中删除项目效率低下，因此取消的计时器将保留在原位，但**标记为已取消**。

消息传输使用计时器功能，使用随机模拟延迟来安排稍后在每个节点上传递消息。我们再次使用 `functools.partial` 设置对目标节点 `receive` 的参数。

运行模拟只需从堆中弹出计时器，并在它们**尚未取消**且目标节点仍处于**活动**状态时执行它们。

```python
class Timer(object):

    def __init__(self, expires, address, callback):
        self.expires = expires
        self.address = address
        self.callback = callback
        self.cancelled = False

    def __cmp__(self, other):
        return cmp(self.expires, other.expires)

    def cancel(self):
        self.cancelled = True


class Network(object):
    PROP_DELAY = 0.03
    PROP_JITTER = 0.02
    DROP_PROB = 0.05

    def __init__(self, seed):
        self.nodes = {}
        self.rnd = random.Random(seed)
        self.timers = []
        self.now = 1000.0

    def new_node(self, address=None):
        node = Node(self, address=address)
        self.nodes[node.address] = node
        return node

    def run(self):
        while self.timers:
            next_timer = self.timers[0]
            if next_timer.expires > self.now:
                self.now = next_timer.expires
            heapq.heappop(self.timers)
            if next_timer.cancelled:
                continue
            if not next_timer.address or next_timer.address in self.nodes:
                next_timer.callback()

    def stop(self):
        self.timers = []

    def set_timer(self, address, seconds, callback):
        timer = Timer(self.now + seconds, address, callback)
        heapq.heappush(self.timers, timer)
        return timer

    def send(self, sender, destinations, message):
        sender.logger.debug("sending %s to %s", message, destinations)
        # avoid aliasing by making a closure containing distinct deep copy of
        # message for each dest
        def sendto(dest, message):
            if dest == sender.address:
                # reliably deliver local messages with no delay
                self.set_timer(sender.address, 0,  
                               lambda: sender.receive(sender.address, message))
            elif self.rnd.uniform(0, 1.0) > self.DROP_PROB:
                delay = self.PROP_DELAY + self.rnd.uniform(-self.PROP_JITTER, 
                                                           self.PROP_JITTER)
                self.set_timer(dest, delay, 
                               functools.partial(self.nodes[dest].receive, 
                                                 sender.address, message))
        for dest in (d for d in destinations if d in self.nodes):
            sendto(dest, copy.deepcopy(message))
```

虽然这个实现中没有包含，但组件模型允许我们在真实世界的网络实现中交换，在真实网络上的实际服务器之间进行通信，而无需更改其他组件。可以使用模拟网络进行测试和调试，生产使用在真实网络硬件上运行。

# 调试支持
在开发这样的复杂系统时，错误会迅速从琐碎的（如简单的 NameError ）过渡到晦涩难懂的故障，这些故障仅在（模拟）proocol 操作几分钟后才会显现出来。像这样的错误需要从错误变得明显的地方向后工作。交互式调试器在这里毫无用处，因为它们只能看到当前情况。

Cluster 中最重要的调试功能是**确定性**模拟器。与真实网络不同，它在每次运行时的行为方式完全相同，给定**随机数生成器的相同种子**。这意味着我们可以在代码中添加额外的调试检查或输出，并重新运行仿真以更详细地查看相同的故障。

当然，大部分细节都存在于集群中节点交换的消息中，因此这些消息会自动完整记录下来。该日志记录包括发送或接收消息的角色类，以及通过 `SimTimeLogger` 类注入的模拟时间戳。
```python
class SimTimeLogger(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return "T=%.3f %s" % (self.extra['network'].now, msg), kwargs
    def getChild(self, name):
        return self.__class__(self.logger.getChild(name),
                              {'network': self.extra['network']})
```
像这样的弹性协议通常可以在触发错误后运行很长时间。例如，在开发过程中，数据别名错误导致所有副本共享同一个 decisions 字典。这意味着，一旦在一个节点上处理了决策，所有其他节点都会将其视为已决定。即使存在此严重错误，集群在死锁之前仍为多个事务生成了正确的结果。

**断言**是及早发现此类错误的重要工具。断言应该包括算法设计中的任何不变量，但是当代码的行为不符合我们的预期时，断言我们的期望是查看事情误入歧途的好方法。
```python
    assert not self.decisions.get(self.slot, None), \
            "next slot to commit is already decided"
    if slot in self.decisions:
        assert self.decisions[slot] == proposal, \
            "slot %d already decided with %r!" % (slot, self.decisions[slot])
```

识别我们在阅读代码时做出的正确假设是调试艺术的一部分。在 `Replica.do_Decision` 的代码中，问题在于下一个要提交的槽位的决策被忽略了，因为它已经在 `self.decisions` 中。被违反的基本假设是下一个要提交的槽位尚未决定。在 `do_Decision` 的开头断言这一点，可以识别出缺陷并迅速修复。同样，其他错误导致在相同槽位中决定了不同的提议——这是一个严重的错误。


在开发协议的过程中，添加了许多其他断言，但为了节省空间，这里只保留了一些。

## 测试

在过去十年的某个时候，没有测试的编码终于变得像不系安全带一样疯狂。没有测试的代码可能是不正确的，如果没有办法查看其行为是否已更改，修改代码是有风险的。

当代码组织为可测试性时，测试是最有效的。在这个领域有一些流派，但我们采取的方法是将代码划分为小的、连接最少的单元，这些**单元可以单独测试**。这与角色模型非常吻合，在角色模型中，每个角色都有特定的目的，并且可以与其他角色独立运作，从而形成一个紧凑、自给自足的类。

Cluster 的编写是为了最大限度地提高这种隔离：角色之间的所有通信都通过消息进行，但创建新角色除外。因此，在大多数情况下，可以通过向角色发送消息并观察其响应来测试角色。

### 单元测试
Cluster 的单元测试简单而简短：
```python
class Tests(utils.ComponentTestCase):
    def test_propose_active(self):
        """A PROPOSE received while active spawns a commander."""
        self.activate_leader()
        self.node.fake_message(Propose(slot=10, proposal=PROPOSAL1))
        self.assertCommanderStarted(Ballot(0, 'F999'), 10, PROPOSAL1)
```

此方法测试单个单位（ Leader 类）的单个行为（commander spawning）。它遵循众所周知的“安排、行动、断言”模式：设置一个活动的领导者，向它发送消息，然后检查结果。


### 依赖注入 dependency injection

我们使用一种称为“**依赖注入**”的技术来处理新角色的创建。向网络添加其他角色的每个角色类都采用类对象列表作为构造函数参数，默认为实际类。例如，构造 Leader 函数如下所示：
```python
class Leader(Role):
    def __init__(self, node, peers, commander_cls=Commander, scout_cls=Scout):
        super(Leader, self).__init__(node)
        self.ballot_num = Ballot(0, node.address)
        self.active = False
        self.proposals = {}
        self.commander_cls = commander_cls
        self.scout_cls = scout_cls
        self.scouting = False
        self.peers = peers
```
`spawn_scout` 方法（ spawn_commander类似 ）使用 `self.scout_cls` 创建新的角色对象：
```python
class Leader(Role):
    def spawn_scout(self):
        assert not self.scouting
        self.scouting = True
        self.scout_cls(self.node, self.ballot_num, self.peers).start()
```

这种技术的神奇之处在于，在测试中， Leader 可以给出假类，从而与 Scout 和 Commander 分开测试。

###  接口正确性
专注于小单元的一个缺陷是它不测试单元之间的接口。例如，接受者角色的单元测试验证 Promise 消息 accepted 属性的格式，而侦查角色的单元测试为属性提供格式正确的值。这两个测试都不会检查这些格式是否匹配。

解决此问题的一种方法是使**接口自我强制执行**。在群集中，使用命名元组和关键字参数可以避免对消息属性的任何分歧。由于角色类之间的唯一交互是通过消息进行的，因此这涵盖了接口的很大一部分。

对于特定问题，例如`accepted_proposals`的格式 ，可以使用相同的函数来验证真实数据和测试数据，在本例 `verifyPromiseAccepted` 中。受体的测试使用这种方法来验证每个返回的，而侦察器的测试则使用它来验证每个假的`Promise` 。

### 集成测试
解决接口问题和设计错误的最后一个堡垒是集成测试。集成测试将多个单元组装在一起，并测试它们的组合效果。在我们的例子中，这意味着构建一个由多个节点组成的网络，向其中注入一些请求，并验证结果。如果在单元测试中未发现任何接口问题，则应导致集成测试快速失败。

由于该协议旨在优雅地处理节点故障，因此我们还测试了一些故障场景，包括活动领导者的不合时宜的故障。

集成测试比单元测试更难编写，因为它们的隔离性较差。对于集群，这在测试失败的领导者时最为明显，因为任何节点都可以是活动的领导者。即使使用确定性网络，一条消息的变化也会改变随机数生成器的状态，从而不可预测地改变后面的事件。测试代码不是对预期的领导者进行硬编码，而是必须深入研究每个领导者的内部状态，以找到一个认为自己处于活动状态的领导者。
### 模糊测试

测试弹性代码非常困难：它可能对自己的错误具有弹性，因此集成测试甚至可能无法检测到非常严重的错误。也很难想象和构建针对每种可能的故障模式的测试。

解决此类问题的一种常见方法是“模糊测试”：使用随机更改的输入重复运行代码，直到出现问题。当某些东西确实出现问题时，所有的调试支持都变得至关重要：如果无法重现故障，并且日志记录信息不足以找到错误，那么你就无法修复它！
我在开发过程中对集群进行了一些手动模糊测试，但完整的模糊测试基础设施超出了本项目的范围。

# 权力斗争
一个有许多活跃领导者的集群是一个非常嘈杂的地方，侦察员向接受者发送越来越多的选票，但没有决定选票。没有活动领导者的集群是安静的，但同样不起作用。平衡实现，使集群几乎总是只同意一个领导者，这是非常困难的。

避免与领导者发生争执很容易：当被抢占时，领导者只会接受其新的不活跃状态。然而，这很容易导致没有活跃领导者的情况，因此不活跃的领导者每次收到 Propose 消息时都会尝试变得活跃。

如果整个集群不同意哪个成员是活跃的领导者，那就有麻烦了：不同的副本向不同的领导者发送 Propose 消息，导致侦察兵的战斗。因此，重要的是迅速决定领导人选举，并且所有集群成员尽快了解结果。


Cluster 通过尽可能快地检测领导者的变化来处理这个问题：当接受者发送 Promise 时，承诺的成员很有可能成为下一个领导者。使用检测信号协议检测故障。

# 进一步扩展
当然，我们有很多方法可以扩展和改进此实现。

## Catching Up 
在“纯”Multi-Paxos 中，无法接收消息的节点可能落后于集群的其余部分。只要分布式状态机的状态除了通过状态机转换之外从不被访问，这种设计就是有效的。为了从状态读取，客户端请求状态机转换，该转换实际上不会更改状态，但返回所需的值。此转换在集群范围内执行，确保它根据建议它的插槽的状态在任何地方返回相同的值。

即使在最佳情况下，这也很慢，需要多次往返才能读取一个值。如果分布式对象存储对每个对象访问都发出这样的请求，则其性能将很糟糕。但是，当接收请求的节点滞后时，请求延迟要大得多，因为该节点必须赶上集群的其余部分才能成功提出建议。


一个简单的解决方案是实现一个八卦风格的协议，其中每个副本定期联系其他副本，以共享它知道的最高插槽，并请求有关未知插槽的信息。然后，即使丢失了 Decision 消息，副本也会很快从其中一个对等方那里发现该决定。

## 一致的内存使用率

集群管理库在存在不可靠组件时提供可靠性。它不应该增加自己的不可靠性。不幸的是，由于内存使用量和消息大小不断增长，Cluster 不会长时间运行而不会失败。

在协议定义中，接受体和副本构成了协议的“内存”，因此它们需要记住所有内容。这些类永远不知道他们什么时候会收到对旧插槽的请求，可能是来自滞后的副本或领导者。因此，为了保持正确性，他们保留了自集群启动以来的每个决策的列表。更糟糕的是，这些决策是在消息中的 Welcome 副本之间传输的，这使得这些消息在长期集群中非常庞大。

解决此问题的一种技术是定期“检查”每个节点的状态，保留有关手头有限数量决策的信息。如果节点已经过时，以至于它们没有将所有插槽提交到检查点，则必须通过离开并重新加入集群来“重置”自己。

## 持久化存储

虽然少数集群成员失败是可以的，但接受者“忘记”它已经接受的任何价值或它所做的承诺是不行的。

不幸的是，这正是集群成员失败并重新启动时发生的情况：新初始化的 Acceptor 实例没有其前身做出的承诺的记录。问题在于新启动的实例取代了旧的实例。

有两种方法可以解决此问题。更简单的解决方案是将接受器状态写入磁盘，并在启动时重新读取该状态。更复杂的解决方案是从集群中删除失败的集群成员，并要求将新成员添加到集群中。这种对集群成员身份的动态调整称为“视图更改”。

## 查看更改
运营工程师需要能够调整群集大小以满足负载和可用性要求。一个简单的测试项目可能从三个节点的最小集群开始，其中任何一个节点都可能失败而不会受到影响。但是，当该项目“上线”时，额外的负载将需要更大的集群。

如前所述，如果不重新启动整个集群，集群就无法更改集群中的对等节点集。理想情况下，集群将能够就其成员身份保持共识，就像它对状态机转换所做的那样。这意味着集群成员集（视图）可以通过特殊的视图更改建议进行更改。但是 Paxos 算法依赖于对集群中成员的普遍共识，因此我们必须为每个插槽定义视图。
Lamport在“Paxos Made Simple”的最后一段中谈到了这一挑战：
我们可以允许领导者通过在执行 第i个状态机命令后由状态指定执行共识算法实例 i+α的服务器集来提前获取 α命令。（兰波特，2001 年）

 这个想法是，Paxos（插槽）的每个实例都使用之前 α给插槽中的视图。这允许集群在任何时候最多处理α个插槽，因此非常小的值 α会限制并发性，而非常大的 α值会使视图更改生效速度变慢。
在这个实现的早期草案中（尽职尽责地保存在 git 历史记录中！），我实现了对视图更改的支持（使用 α 代替 3）。这个看似简单的更改带来了很大的复杂性：

- 跟踪每个最后 α提交的插槽的视图，并正确地与新节点共享，
- 忽略没有可用位置的提案，
- 检测故障节点，
- 正确序列化多个竞争视图更改
- 在主目录和副本之间传递视图信息。

结果对这本书来说太大了！
