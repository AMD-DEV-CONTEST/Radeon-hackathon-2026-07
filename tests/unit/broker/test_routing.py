from cortex.broker.routing import Router, Subscriber


def make_sub(node_id: str, org_did: str, topics, scopes, ws=None) -> Subscriber:
    return Subscriber(
        node_id=node_id,
        org_did=org_did,
        topics=set(topics),
        scopes=set(scopes),
        ws=ws,
    )


def test_subscribe_is_idempotent():
    r = Router()
    s = make_sub("node-A", "did:percq:org:soc-alpha", ["threat-intel"], ["public"])
    r.subscribe(s)
    r.subscribe(s)
    subs = r.subscribers_for(
        topic="threat-intel", scope="public", src_org="did:percq:org:soc-alpha",
    )
    assert len(subs) == 1


def test_subscribers_for_matches_topic_and_acl():
    r = Router()
    alpha = make_sub("A", "did:percq:org:soc-alpha", ["apt29"], ["public"])
    beta = make_sub("B", "did:percq:org:soc-beta", ["apt29"], ["public"])
    r.subscribe(alpha)
    r.subscribe(beta)
    subs = r.subscribers_for(topic="apt29", scope="public", src_org="did:percq:org:soc-alpha")
    ids = {s.node_id for s in subs}
    assert ids == {"A", "B"}


def test_subscribers_for_excludes_wrong_topic():
    r = Router()
    alpha = make_sub("A", "did:percq:org:soc-alpha", ["threat-intel"], ["public"])
    beta = make_sub("B", "did:percq:org:soc-beta", ["apt29"], ["public"])
    r.subscribe(alpha)
    r.subscribe(beta)
    subs = r.subscribers_for(topic="apt29", scope="public", src_org="did:percq:org:soc-alpha")
    assert {s.node_id for s in subs} == {"B"}


def test_subscribers_for_acl_blocks_partner_other():
    r = Router()
    alpha = make_sub("A", "did:percq:org:soc-alpha", ["apt29"], ["partner:did:percq:org:soc-alpha"])
    beta = make_sub("B", "did:percq:org:soc-beta", ["apt29"], ["partner:did:percq:org:soc-alpha"])
    r.subscribe(alpha)
    r.subscribe(beta)
    subs_alpha_scope = r.subscribers_for(topic="apt29", scope="partner:did:percq:org:soc-alpha",
                                         src_org="did:percq:org:soc-beta")
    assert {s.node_id for s in subs_alpha_scope} == {"A"}


def test_subscribers_for_intra_org_passes_private_scope():
    r = Router()
    alpha = make_sub("A", "did:percq:org:soc-alpha", ["apt29"], ["private"])
    r.subscribe(alpha)
    subs = r.subscribers_for(topic="apt29", scope="private", src_org="did:percq:org:soc-alpha")
    assert {s.node_id for s in subs} == {"A"}


def test_subscribers_for_blocks_private_cross_org():
    r = Router()
    alpha = make_sub("A", "did:percq:org:soc-alpha", ["apt29"], ["private"])
    r.subscribe(alpha)
    subs = r.subscribers_for(topic="apt29", scope="private", src_org="did:percq:org:soc-beta")
    assert subs == []


def test_unsubscribe_removes_subscriber():
    r = Router()
    s = make_sub("A", "did:percq:org:soc-alpha", ["apt29"], ["public"])
    r.subscribe(s)
    assert len(r.subscribers_for("apt29", "public", "did:percq:org:soc-alpha")) == 1
    r.unsubscribe("A")
    assert r.subscribers_for("apt29", "public", "did:percq:org:soc-alpha") == []
