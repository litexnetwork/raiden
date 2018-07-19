from raiden.transfer.architecture import StateManager


def restore_from_latest_snapshot(transition_function, storage):
    events = list()
    snapshot = storage.get_state_snapshot()

    if snapshot:
        last_applied_state_change_id, state = snapshot
        unapplied_state_changes = storage.get_statechanges_by_identifier(
            from_identifier=last_applied_state_change_id,
            to_identifier='latest',
        )
    else:
        state = None
        unapplied_state_changes = storage.get_statechanges_by_identifier(
            from_identifier=0,
            to_identifier='latest',
        )

    state_manager = StateManager(transition_function, state)
    wal = WriteAheadLog(state_manager, storage)

    for state_change in unapplied_state_changes:
        events.extend(state_manager.dispatch(state_change))

    return wal, events


class WriteAheadLog:
    def __init__(self, state_manager, storage):
        self.state_manager = state_manager
        self.state_change_id = None
        self.storage = storage

    def log_and_dispatch(self, state_change, block_number):
        """ Log and apply a state change.

        This function will first write the state change to the write-ahead-log,
        in case of a node crash the state change can be recovered and replayed
        to restore the node state.

        Events produced by applying state change are also saved.
        """
        state_change_id = self.storage.write_state_change(state_change)

        events = self.state_manager.dispatch(state_change)

        self.state_change_id = state_change_id
        self.storage.write_events(state_change_id, block_number, events)

        return events

    def snapshot(self):
        """ Snapshot the application state.

        Snapshots are used to restore the application state, either after a
        restart or a crash.
        """
        current_state = self.state_manager.current_state
        state_change_id = self.state_change_id

        # otherwise no state change was dispatched
        if state_change_id:
            self.storage.write_state_snapshot(state_change_id, current_state)

####demo
class CrossTransaction:
    def __init__(self, state_manager, storage):
        self.state_manager = state_manager
        self.state_change_id = None
        self.storage = storage

    def crosstransactiontry(self, initiator_address, target_address, sendETH_amount, sendBTC_amount, receiveBTC_address, sendBTC_address, time, status):
        """ Log and apply a state change.

        This function will first write the state change to the write-ahead-log,
        in case of a node crash the state change can be recovered and replayed
        to restore the node state.

        Events produced by applying state change are also saved.
        """

        ###events = self.state_manager.dispatch(state_change)

        identifier = self.storage.write_crosstransaction_events(initiator_address, target_address, sendETH_amount, sendBTC_amount, receiveBTC_address, sendBTC_address, time, status)

        return identifier

    def get_crosstransaction(self,address):
        """ Snapshot the application state.

        Snapshots are used to restore the application state, either after a
        restart or a crash.
        """
        transactions = self.storage.get_crosstransaction_events(address)
        return transactions
