import pytest

# noinspection PyUnresolvedReferences
from ledger.test.conftest import tempdir, txn_serializer, hash_serializer  # noqa
from plenum.common.constants import LedgerState, CURRENT_PROTOCOL_VERSION, AUDIT_LEDGER_ID, TXN_PAYLOAD_DATA, \
    TXN_PAYLOAD, AUDIT_TXN_VIEW_NO, AUDIT_TXN_PP_SEQ_NO
from plenum.common.messages.node_messages import LedgerStatus

nodeCount = 7

ledger_id = 1


@pytest.yield_fixture(scope="function")
def node_and_leecher(txnPoolNodeSet):
    '''
    Emulate restart of the node (clean state)
    '''
    node = txnPoolNodeSet[0]

    node.master_replica.last_ordered_3pc = (0, 0)

    for replica in node.replicas.values():
        replica.primaryName = None

    view_changer = node.view_changer
    view_changer.propagate_primary = True
    view_changer.view_no = 0
    view_changer.view_change_in_progress = True
    view_changer.set_defaults()

    ledger_manager = node.ledgerManager
    ledger_manager.last_caught_up_3PC = (0, 0)

    leecher = ledger_manager._leechers[ledger_id].service
    leecher.start(request_ledger_statuses=False)

    ledger_status = node.build_ledger_status(ledger_id)
    assert ledger_status.viewNo is None
    assert ledger_status.ppSeqNo is None

    return node, leecher, ledger_status, leecher._cons_proof_service


def test_same_ledger_status_quorum(txnPoolNodeSet,
                                   node_and_leecher):
    '''
    Check that we require at least n-f-1 (=4) same LedgerStatus msgs
    to finish CatchUp
    '''
    node, leecher, ledger_status, cons_proof_service = node_and_leecher

    status_from = set()
    for i in range(3):
        node_name = txnPoolNodeSet[i + 1].name
        cons_proof_service.process_ledger_status(ledger_status, node_name)
        status_from = status_from.union({node_name})
        assert cons_proof_service._same_ledger_status == status_from
        assert leecher.state == LedgerState.not_synced

    node = txnPoolNodeSet[4]
    cons_proof_service.process_ledger_status(ledger_status, node.name)

    assert cons_proof_service._same_ledger_status == set()
    assert leecher.state == LedgerState.synced


def test_same_ledger_status_last_ordered_same_3PC(txnPoolNodeSet,
                                                  node_and_leecher,
                                                  monkeypatch):
    '''
    Check that last_ordered_3PC is set according to 3PC from LedgerStatus msgs
    if all LedgerStatus msgs have the same not None 3PC keys
    '''
    node, leecher, ledger_status_none_3PC, cons_proof_service = node_and_leecher
    ledger_status_2_40 = LedgerStatus(ledger_status_none_3PC.ledgerId,
                                      ledger_status_none_3PC.txnSeqNo,
                                      2, 20,
                                      ledger_status_none_3PC.merkleRoot,
                                      CURRENT_PROTOCOL_VERSION)
    monkeypatch.setattr(node.getLedger(AUDIT_LEDGER_ID),
                        'get_last_committed_txn',
                        lambda: {TXN_PAYLOAD: {TXN_PAYLOAD_DATA: {AUDIT_TXN_VIEW_NO: ledger_status_2_40.viewNo,
                                                                  AUDIT_TXN_PP_SEQ_NO: ledger_status_2_40.ppSeqNo}}})
    cons_proof_service.process_ledger_status(ledger_status_2_40, txnPoolNodeSet[1].name)
    cons_proof_service.process_ledger_status(ledger_status_2_40, txnPoolNodeSet[2].name)
    cons_proof_service.process_ledger_status(ledger_status_2_40, txnPoolNodeSet[3].name)
    assert node.master_last_ordered_3PC == (0, 0)
    assert leecher.state == LedgerState.not_synced

    cons_proof_service.process_ledger_status(ledger_status_2_40, txnPoolNodeSet[4].name)
    monkeypatch.undo()
    assert node.master_last_ordered_3PC == (2, 20)
    assert leecher.state == LedgerState.synced


def test_same_ledger_status_last_ordered_same_None_3PC(txnPoolNodeSet,
                                                       node_and_leecher,
                                                       monkeypatch):
    '''
    Check that last_ordered_3PC is set according to 3PC from LedgerStatus msgs
    if all LedgerStatus msgs have the same None 3PC keys (like at the initial start of the pool)
    '''
    node, leecher, ledger_status_none_3PC, cons_proof_service = node_and_leecher

    monkeypatch.setattr(node.getLedger(AUDIT_LEDGER_ID),
                        'get_last_committed_txn',
                        lambda: {TXN_PAYLOAD: {TXN_PAYLOAD_DATA: {AUDIT_TXN_VIEW_NO: ledger_status_none_3PC.viewNo,
                                                                  AUDIT_TXN_PP_SEQ_NO: ledger_status_none_3PC.ppSeqNo}}})
    cons_proof_service.process_ledger_status(ledger_status_none_3PC, txnPoolNodeSet[1].name)
    cons_proof_service.process_ledger_status(ledger_status_none_3PC, txnPoolNodeSet[2].name)
    cons_proof_service.process_ledger_status(ledger_status_none_3PC, txnPoolNodeSet[3].name)
    assert node.master_last_ordered_3PC == (0, 0)
    assert leecher.state == LedgerState.not_synced

    cons_proof_service.process_ledger_status(ledger_status_none_3PC, txnPoolNodeSet[4].name)
    monkeypatch.undo()
    assert node.master_last_ordered_3PC == (0, 0)
    assert leecher.state == LedgerState.synced


def test_same_ledger_status_last_ordered_one_not_none_3PC_last(txnPoolNodeSet,
                                                               node_and_leecher,
                                                  monkeypatch):
    '''
    Check that last_ordered_3PC is set according to 3PC from LedgerStatus msgs
    if all LedgerStatus msgs have the same None 3PC keys except the last one.
    The last msg contains not None 3PC, but it's not enough for setting last_ordered_3PC
    since the quorum is f+1 (=3)
    '''
    node, leecher, ledger_status_none_3PC, cons_proof_service = node_and_leecher

    ledger_status_3_40 = LedgerStatus(ledger_status_none_3PC.ledgerId,
                                      ledger_status_none_3PC.txnSeqNo,
                                      3, 40,
                                      ledger_status_none_3PC.merkleRoot,
                                      CURRENT_PROTOCOL_VERSION)

    monkeypatch.setattr(node.getLedger(AUDIT_LEDGER_ID),
                        'get_last_committed_txn',
                        lambda: {TXN_PAYLOAD: {TXN_PAYLOAD_DATA: {AUDIT_TXN_VIEW_NO: ledger_status_3_40.viewNo,
                                                                  AUDIT_TXN_PP_SEQ_NO: ledger_status_3_40.ppSeqNo}}})
    cons_proof_service.process_ledger_status(ledger_status_none_3PC, txnPoolNodeSet[1].name)
    cons_proof_service.process_ledger_status(ledger_status_none_3PC, txnPoolNodeSet[2].name)
    cons_proof_service.process_ledger_status(ledger_status_none_3PC, txnPoolNodeSet[3].name)
    assert node.master_last_ordered_3PC == (0, 0)
    assert leecher.state == LedgerState.not_synced

    cons_proof_service.process_ledger_status(ledger_status_3_40, txnPoolNodeSet[4].name)
    monkeypatch.undo()
    assert node.master_last_ordered_3PC == (0, 0)
    assert leecher.state == LedgerState.synced


def test_same_ledger_status_last_ordered_one_not_none_3PC_first(txnPoolNodeSet,
                                                                node_and_leecher,
                                                       monkeypatch):
    '''
    Check that last_ordered_3PC is set according to 3PC from LedgerStatus msgs
    if all LedgerStatus msgs have the same None 3PC keys except the first one.
    The first msg contains not None 3PC, but it's not enough for setting last_ordered_3PC
    since the quorum is f+1 (=3)
    '''
    node, leecher, ledger_status_none_3PC, cons_proof_service = node_and_leecher

    ledger_status_3_40 = LedgerStatus(ledger_status_none_3PC.ledgerId,
                                      ledger_status_none_3PC.txnSeqNo,
                                      3, 40,
                                      ledger_status_none_3PC.merkleRoot,
                                      CURRENT_PROTOCOL_VERSION)

    monkeypatch.setattr(node.getLedger(AUDIT_LEDGER_ID),
                        'get_last_committed_txn',
                        lambda: {TXN_PAYLOAD: {TXN_PAYLOAD_DATA: {AUDIT_TXN_VIEW_NO: ledger_status_3_40.viewNo,
                                                                  AUDIT_TXN_PP_SEQ_NO: ledger_status_3_40.ppSeqNo}}})
    cons_proof_service.process_ledger_status(ledger_status_3_40, txnPoolNodeSet[1].name)
    cons_proof_service.process_ledger_status(ledger_status_none_3PC, txnPoolNodeSet[2].name)
    cons_proof_service.process_ledger_status(ledger_status_none_3PC, txnPoolNodeSet[3].name)
    assert node.master_last_ordered_3PC == (0, 0)
    assert leecher.state == LedgerState.not_synced

    cons_proof_service.process_ledger_status(ledger_status_none_3PC, txnPoolNodeSet[4].name)
    monkeypatch.undo()
    assert node.master_last_ordered_3PC == (0, 0)
    assert leecher.state == LedgerState.synced


def test_same_ledger_status_last_ordered_not_none_3PC_quorum_with_none(txnPoolNodeSet,
                                                                       node_and_leecher,
                                                       monkeypatch):
    '''
    Check that last_ordered_3PC is set according to 3PC from LedgerStatus msgs
    if all LedgerStatus msgs have the same not None 3PC keys except the last one.
    The last msg contains None 3PC, but not None from the previous msgs is used
    since we have a quorum of f+1 (=3)
    '''
    node, leecher, ledger_status_none_3PC, cons_proof_service = node_and_leecher

    ledger_status_3_40 = LedgerStatus(ledger_status_none_3PC.ledgerId,
                                      ledger_status_none_3PC.txnSeqNo,
                                      3, 40,
                                      ledger_status_none_3PC.merkleRoot,
                                      CURRENT_PROTOCOL_VERSION)
    monkeypatch.setattr(node.getLedger(AUDIT_LEDGER_ID),
                        'get_last_committed_txn',
                        lambda: {TXN_PAYLOAD: {TXN_PAYLOAD_DATA: {AUDIT_TXN_VIEW_NO: ledger_status_3_40.viewNo,
                                                                  AUDIT_TXN_PP_SEQ_NO: ledger_status_3_40.ppSeqNo}}})
    cons_proof_service.process_ledger_status(ledger_status_3_40, txnPoolNodeSet[1].name)
    cons_proof_service.process_ledger_status(ledger_status_3_40, txnPoolNodeSet[2].name)
    cons_proof_service.process_ledger_status(ledger_status_3_40, txnPoolNodeSet[3].name)
    assert node.master_last_ordered_3PC == (0, 0)
    assert leecher.state == LedgerState.not_synced

    cons_proof_service.process_ledger_status(ledger_status_none_3PC, txnPoolNodeSet[4].name)
    monkeypatch.undo()
    assert node.master_last_ordered_3PC == (3, 40)
    assert leecher.state == LedgerState.synced


def test_same_ledger_status_last_ordered_not_none_3PC_quorum1(txnPoolNodeSet,
                                                              node_and_leecher,
                                                       monkeypatch):
    '''
    Check that last_ordered_3PC is set according to 3PC from LedgerStatus msgs
    if all LedgerStatus msgs have the same not None 3PC keys except the last one.
    The last msg contains a different not None 3PC, but 3PC from the previous msgs is used
    since we have a quorum of f+1 (=3)
    '''
    node, leecher, ledger_status_none_3PC, cons_proof_service = node_and_leecher

    ledger_status_1_10 = LedgerStatus(ledger_status_none_3PC.ledgerId,
                                      ledger_status_none_3PC.txnSeqNo,
                                      1, 10,
                                      ledger_status_none_3PC.merkleRoot,
                                      CURRENT_PROTOCOL_VERSION)

    ledger_status_3_40 = LedgerStatus(ledger_status_none_3PC.ledgerId,
                                      ledger_status_none_3PC.txnSeqNo,
                                      3, 40,
                                      ledger_status_none_3PC.merkleRoot,
                                      CURRENT_PROTOCOL_VERSION)

    monkeypatch.setattr(node.getLedger(AUDIT_LEDGER_ID),
                        'get_last_committed_txn',
                        lambda: {TXN_PAYLOAD: {TXN_PAYLOAD_DATA: {AUDIT_TXN_VIEW_NO: ledger_status_1_10.viewNo,
                                                                  AUDIT_TXN_PP_SEQ_NO: ledger_status_1_10.ppSeqNo}}})
    cons_proof_service.process_ledger_status(ledger_status_1_10, txnPoolNodeSet[1].name)
    cons_proof_service.process_ledger_status(ledger_status_1_10, txnPoolNodeSet[2].name)
    cons_proof_service.process_ledger_status(ledger_status_1_10, txnPoolNodeSet[3].name)
    assert node.master_last_ordered_3PC == (0, 0)
    assert leecher.state == LedgerState.not_synced

    monkeypatch.setattr(node.getLedger(AUDIT_LEDGER_ID),
                        'get_last_committed_txn',
                        lambda: {TXN_PAYLOAD: {TXN_PAYLOAD_DATA: {AUDIT_TXN_VIEW_NO: ledger_status_3_40.viewNo,
                                                                  AUDIT_TXN_PP_SEQ_NO: ledger_status_3_40.ppSeqNo}}})
    cons_proof_service.process_ledger_status(ledger_status_3_40, txnPoolNodeSet[4].name)
    monkeypatch.undo()
    assert node.master_last_ordered_3PC == (1, 10)
    assert leecher.state == LedgerState.synced


def test_same_ledger_status_last_ordered_not_none_3PC_quorum2(txnPoolNodeSet,
                                                              node_and_leecher,
                                                       monkeypatch):
    '''
    Check that last_ordered_3PC is set according to 3PC from LedgerStatus msgs
    if all LedgerStatus msgs have the same not None 3PC keys except the last one.
    The last msg contains a different not None 3PC, but 3PC from the previous msgs is used
    since we have a quorum of f+1 (=3)
    '''
    node, leecher, ledger_status_none_3PC, cons_proof_service = node_and_leecher

    ledger_status_1_10 = LedgerStatus(ledger_status_none_3PC.ledgerId,
                                      ledger_status_none_3PC.txnSeqNo,
                                      1, 10,
                                      ledger_status_none_3PC.merkleRoot,
                                      CURRENT_PROTOCOL_VERSION)

    ledger_status_3_40 = LedgerStatus(ledger_status_none_3PC.ledgerId,
                                      ledger_status_none_3PC.txnSeqNo,
                                      3, 40,
                                      ledger_status_none_3PC.merkleRoot,
                                      CURRENT_PROTOCOL_VERSION)
    monkeypatch.setattr(node.getLedger(AUDIT_LEDGER_ID),
                        'get_last_committed_txn',
                        lambda: {TXN_PAYLOAD: {TXN_PAYLOAD_DATA: {AUDIT_TXN_VIEW_NO: ledger_status_3_40.viewNo,
                                                                  AUDIT_TXN_PP_SEQ_NO: ledger_status_3_40.ppSeqNo}}})
    cons_proof_service.process_ledger_status(ledger_status_3_40, txnPoolNodeSet[1].name)
    cons_proof_service.process_ledger_status(ledger_status_3_40, txnPoolNodeSet[2].name)
    cons_proof_service.process_ledger_status(ledger_status_3_40, txnPoolNodeSet[3].name)
    assert node.master_last_ordered_3PC == (0, 0)
    assert leecher.state == LedgerState.not_synced

    monkeypatch.setattr(node.getLedger(AUDIT_LEDGER_ID),
                        'get_last_committed_txn',
                        lambda: {TXN_PAYLOAD: {TXN_PAYLOAD_DATA: {AUDIT_TXN_VIEW_NO: ledger_status_1_10.viewNo,
                                                                  AUDIT_TXN_PP_SEQ_NO: ledger_status_1_10.ppSeqNo}}})
    cons_proof_service.process_ledger_status(ledger_status_1_10, txnPoolNodeSet[4].name)
    monkeypatch.undo()
    assert node.master_last_ordered_3PC == (3, 40)
    assert leecher.state == LedgerState.synced


def test_same_ledger_status_last_ordered_not_none_3PC_no_quorum_equal(txnPoolNodeSet,
                                                                      node_and_leecher,
                                                       monkeypatch):
    '''
    Check that last_ordered_3PC is set according to 3PC from LedgerStatus msgs.
    Check that if we have no quorum (2 different keys, but 3 is required ror quorum), then
    they are not used.
    '''
    node, leecher, ledger_status_none_3PC, cons_proof_service = node_and_leecher

    ledger_status_1_10 = LedgerStatus(ledger_status_none_3PC.ledgerId,
                                      ledger_status_none_3PC.txnSeqNo,
                                      1, 10,
                                      ledger_status_none_3PC.merkleRoot,
                                      CURRENT_PROTOCOL_VERSION)

    ledger_status_3_40 = LedgerStatus(ledger_status_none_3PC.ledgerId,
                                      ledger_status_none_3PC.txnSeqNo,
                                      3, 40,
                                      ledger_status_none_3PC.merkleRoot,
                                      CURRENT_PROTOCOL_VERSION)

    cons_proof_service.process_ledger_status(ledger_status_3_40, txnPoolNodeSet[1].name)
    cons_proof_service.process_ledger_status(ledger_status_3_40, txnPoolNodeSet[2].name)
    cons_proof_service.process_ledger_status(ledger_status_1_10, txnPoolNodeSet[3].name)
    assert node.master_last_ordered_3PC == (0, 0)
    assert leecher.state == LedgerState.not_synced

    cons_proof_service.process_ledger_status(ledger_status_1_10, txnPoolNodeSet[4].name)
    assert node.master_last_ordered_3PC == (0, 0)
    assert leecher.state == LedgerState.synced
