"""Four checks, one per verdict. Run: pytest examples/router"""

import falsetto
import router

_original_pick_route = router.pick_route


def pick_route_dropping_thread_key(msg):
    route = _original_pick_route(msg)
    return router.Route(thread_key=None, queue=route.queue)


def pick_route_to_wrong_queue(msg):
    route = _original_pick_route(msg)
    return router.Route(thread_key=route.thread_key, queue="wrong")


# PROVEN: passes as written; under "pick_route drops the thread key" the assertion trips.
@falsetto.must_fail_when(lambda m: m.setattr(router, "pick_route", pick_route_dropping_thread_key))
def test_route_keeps_thread_key(msg):
    route = router.pick_route(msg)
    assert route.thread_key == msg.thread_key


# FAILED: an ordinary red check. Falsetto changes nothing here.
def test_route_queue_is_billing(msg):
    assert router.pick_route(msg).queue == "billing"


# FALSE: the expected value is derived from the subject, so the assertion compares
# the subject to itself. Under the declared change both sides move together.
@falsetto.must_fail_when(lambda m: m.setattr(router, "pick_route", pick_route_to_wrong_queue))
def test_route_queue_matches(msg):
    expected = router.pick_route(msg).queue
    assert router.pick_route(msg).queue == expected


# UNPROVEN: no declaration. Nothing is known about this check yet.
def test_ops_body_routes_to_ops(msg):
    assert router.pick_route(msg).queue == "ops"
