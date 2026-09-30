from airpods_linux.ear import PAUSE, RESUME, RESUME_WINDOW_S, EarPauseLogic


def run(steps, connected=True):
    logic, out = EarPauseLogic(), []
    for i, (l, r) in enumerate(steps):
        out.append(logic.update(l, r, connected, now=float(i)))
    return out


def test_remove_one_of_two_pauses_and_putting_it_back_resumes():
    assert run([(True, True), (False, True), (True, True)]) == [None, PAUSE, RESUME]


def test_remove_right_pauses_too():
    assert run([(True, True), (True, False), (True, True)]) == [None, PAUSE, RESUME]


def test_one_in_case_other_in_ear():
    # izquierdo en la caja (fuera de la oreja), derecho puesto: quitarse el derecho pausa
    assert run([(False, True), (False, False), (False, True)]) == [None, PAUSE, RESUME]


def test_removing_both_pauses_once_and_does_not_resume():
    assert run([(True, True), (False, True), (False, False), (True, True)]) == [None, PAUSE, None, None]


def test_putting_the_other_one_back_does_not_resume():
    # te quitas el izquierdo; ponerte... el derecho ya estaba: solo vuelve el izquierdo reanuda
    assert run([(True, True), (False, True), (False, True)]) == [None, PAUSE, None]


def test_inserting_a_bud_without_previous_pause_does_nothing():
    assert run([(False, False), (True, False), (True, True)]) == [None, None, None]


def test_bud_from_hand_to_case_does_nothing():
    assert run([(False, True), (False, True)]) == [None, None]


def test_unknown_initial_state_does_not_pause():
    assert run([(None, None), (False, False)]) == [None, None]


def test_not_connected_to_this_computer_does_nothing():
    assert run([(True, True), (False, True)], connected=False) == [None, None]


def test_resume_window_expires():
    logic = EarPauseLogic()
    logic.update(True, True, True, 0)
    assert logic.update(False, True, True, 1) == PAUSE
    assert logic.update(True, True, True, 1 + RESUME_WINDOW_S + 1) is None


def test_disconnect_forgets_pending_resume():
    logic = EarPauseLogic()
    logic.update(True, True, True, 0)
    logic.update(False, True, True, 1)
    logic.update(False, True, False, 2)
    assert logic.update(True, True, True, 3) is None
