from agent.forwarding_rules import owned_ports


def test_only_exact_owned_tunnel_rules_are_selected():
    rule = '-A INPUT -i tun0 -p tcp -m tcp --dport 45000 -m comment --comment "mediahub-torrent-pf" -j ACCEPT'
    assert owned_ports(rule) == {("tcp", 45000)}
    assert owned_ports(rule.replace(" -m tcp", "")) == {("tcp", 45000)}
    for unsafe in [
        rule.replace("tun0", "eth0"),
        rule.replace("45000", "22"),
        rule.replace("mediahub-torrent-pf", "other-owner"),
        rule + " -s 192.168.1.1",
        rule.replace("INPUT", "OUTPUT"),
    ]:
        assert owned_ports(unsafe) == set()
