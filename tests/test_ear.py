from airpods_linux.ear import PAUSE, RESUME, RESUME_WINDOW_S, EarPauseLogic


def run(steps, connected=True, source="helper"):
    logic, out = EarPauseLogic(), []
    for i, (l, r) in enumerate(steps):
        out.append(logic.update(source, l, r, connected, now=float(i)))
    return out


def test_remove_one_of_two_pauses_and_putting_it_back_resumes():
    assert run([(True, True), (False, True), (True, True)]) == [None, PAUSE, RESUME]


def test_remove_right_pauses_too():
    assert run([(True, True), (True, False), (True, True)]) == [None, PAUSE, RESUME]


def test_one_in_case_other_in_ear():
    # izquierdo en la caja (fuera de la oreja), derecho puesto: quitarse el derecho pausa
    assert run([(False, True), (False, False), (False, True)]) == [None, PAUSE, RESUME]


def test_one_in_case_side_labels_swapped_between_reports():
    # con un auricular en la caja, las fuentes pueden no coincidir en el lado: da igual
    assert run([(True, False), (False, False), (False, True)]) == [None, PAUSE, RESUME]


def test_removing_both_pauses_once_and_does_not_resume():
    assert run([(True, True), (False, True), (False, False), (True, True)]) == [None, PAUSE, None, None]


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
    logic.update("helper", True, True, True, 0)
    assert logic.update("helper", False, True, True, 1) == PAUSE
    assert logic.update("helper", True, True, True, 1 + RESUME_WINDOW_S + 1) is None


def test_disconnect_forgets_pending_resume():
    logic = EarPauseLogic()
    logic.update("helper", True, True, True, 0)
    logic.update("helper", False, True, True, 1)
    logic.update("helper", False, True, False, 2)
    assert logic.update("helper", True, True, True, 3) is None


# --- dos fuentes: airpods-helper (rápido, mudo con uno en la caja) y BLE (lento) ---

def test_ble_catches_removal_when_helper_goes_silent():
    # Caso real (18:18): helper dice "derecho puesto" y se calla; BLE ve 1→0 y luego 0→1.
    logic = EarPauseLogic()
    assert logic.update("helper", False, True, True, 0) is None
    assert logic.update("ble", True, False, True, 1) is None      # BLE con los lados al revés
    assert logic.update("ble", False, False, True, 10) == PAUSE
    assert logic.update("helper", False, True, True, 11) is None  # helper repite lo de antes
    assert logic.update("ble", True, False, True, 20) == RESUME


def test_late_ble_report_does_not_undo_helper():
    logic = EarPauseLogic()
    logic.update("helper", True, True, True, 0)
    logic.update("ble", True, True, True, 0)
    assert logic.update("helper", False, True, True, 1) == PAUSE
    assert logic.update("ble", True, True, True, 2) is None       # anuncio atrasado: sin cambio para BLE
    assert logic.update("ble", False, True, True, 4) is None      # BLE se entera tarde: ya estaba pausado
    assert logic.update("helper", True, True, True, 6) == RESUME
    assert logic.update("ble", True, True, True, 8) is None       # BLE confirma tarde: no reanuda dos veces
