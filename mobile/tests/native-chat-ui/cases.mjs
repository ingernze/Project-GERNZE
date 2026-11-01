export const cases=[
 ['priority','回复展示与可靠保存先于摘要，最多两次'],
 ['resume','下一次发送抢占摘要且原生单槽不重叠'],
 ['disable','界面关闭自动摘要停止后续批次'],
 ['session','界面切换会话停止旧摘要'],
 ['visibility','visibilitychange 后台事件停止摘要'],
 ['app','app-active=false 停止摘要'],
 ['pagehide','pagehide 销毁停止摘要与接收晚到'],
 ['cancel-chat','界面停止聊天后晚到结果不落库'],
 ['native-busy','原生取消未退出时新发送有限等待并返回 busy'],
 ['timeout','18秒摘要超时与原生单槽退出'],
 ['save-failure','原文保存失败不启动摘要'],
 ['layers','恶意模型字段不能改第一层或第二层']
];
