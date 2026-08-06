#!/bin/bash
echo "========================= 服务器SSH&网络信息自检 ========================="
echo -e "\n【1】服务器公网出口IP（SSH连接使用的IP）"
curl -s ifconfig.me
echo ""
echo -e "\n【2】本机内网IP列表"
hostname -I
echo ""
echo -e "\n【3】SSH服务sshd运行状态"
if command -v systemctl &>/dev/null;then
    systemctl status sshd --no-pager
else
    echo "无systemctl，检测sshd进程"
    ps aux | grep sshd
fi
echo ""
echo -e "\n【4】防火墙ufw规则（查看22端口是否放行）"
if command -v ufw &>/dev/null;then
    ufw status
else
    echo "未安装ufw防火墙"
fi
echo ""
echo -e "\n【5】服务器本地自测SSH 22端口连通性"
if command -v nc &>/dev/null;then
    nc -zv 127.0.0.1 22
else
    echo "nc工具缺失，安装中..."
    apt update && apt install netcat -y
    nc -zv 127.0.0.1 22
fi
echo ""
echo "=========================================================================="
echo "提示：若本地电脑ssh连接超时，代表平台外层防火墙封禁外部SSH接入，端口转发无法使用"
