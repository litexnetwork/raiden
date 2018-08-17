import sqlite3
import threading

from eth_utils import to_normalized_address

from raiden.utils import sha3
from raiden.exceptions import InvalidDBData
from raiden.storage.utils import DB_SCRIPT_CREATE_TABLES
from typing import (
    Any,
    Optional,
    Tuple,
)

# The latest DB version
RAIDEN_DB_VERSION = 0


class SQLiteStorage:
    def __init__(self, database_path, serializer):
        conn = sqlite3.connect(database_path)
        conn.text_factory = str
        conn.execute('PRAGMA foreign_keys=ON')
        self.conn = conn

        with conn:
            try:
                conn.executescript(DB_SCRIPT_CREATE_TABLES)
            except sqlite3.DatabaseError:
                raise InvalidDBData(
                    'Existing DB {} was found to be corrupt at Raiden startup. '
                    'Manual user intervention required. Bailing ...'.format(database_path),
                )

        self._run_updates()

        # When writting to a table where the primary key is the identifier and we want
        # to return said identifier we use cursor.lastrowid, which uses sqlite's last_insert_rowid
        # https://github.com/python/cpython/blob/2.7/Modules/_sqlite/cursor.c#L727-L732
        #
        # According to the documentation (http://www.sqlite.org/c3ref/last_insert_rowid.html)
        # if a different thread tries to use the same connection to write into the table
        # while we query the last_insert_rowid, the result is unpredictable. For that reason
        # we have this write lock here.
        #
        # TODO (If possible):
        # Improve on this and find a better way to protect against this potential race
        # condition.
        self.write_lock = threading.Lock()
        self.serializer = serializer

    def _run_updates(self):
        # TODO: Here add upgrade mechanism depending on the version
        # current_version = self.get_version()

        # And finally at the end write the latest version in the DB
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO settings(name, value) VALUES(?, ?)',
            ('version', str(RAIDEN_DB_VERSION)),
        )
        self.conn.commit()

    def get_version(self) -> int:
        cursor = self.conn.cursor()
        query = cursor.execute(
            'SELECT value FROM settings WHERE name=?;', ('version',),
        )
        query = query.fetchall()
        # If setting is not set, it's the latest version
        if len(query) == 0:
            return RAIDEN_DB_VERSION

        return int(query[0][0])

    def write_state_change(self, state_change):
        serialized_data = self.serializer.serialize(state_change)

        with self.write_lock, self.conn:
            cursor = self.conn.execute(
                'INSERT INTO state_changes(identifier, data) VALUES(null, ?)',
                (serialized_data,),
            )
            last_id = cursor.lastrowid

        return last_id

    def write_state_snapshot(self, statechange_id, snapshot):
        # TODO: Snapshotting is not yet implemented. This is just skeleton code
        # (Issue #682)
        #
        # This skeleton code assumes we only keep a single snapshot and
        # overwrite it each time.
        serialized_data = self.serializer.serialize(snapshot)

        with self.write_lock, self.conn:
            cursor = self.conn.execute(
                'INSERT OR REPLACE INTO state_snapshot('
                '    identifier, statechange_id, data'
                ') VALUES(?, ?, ?)',
                (1, statechange_id, serialized_data),
            )
            last_id = cursor.lastrowid

        return last_id

    def write_events(self, state_change_id, block_number, events):
        """ Save events.

        Args:
            state_change_id: Id of the state change that generate these events.
            block_number: Block number at which the state change was applied.
            events: List of Event objects.
        """
        events_data = [
            (None, state_change_id, block_number, self.serializer.serialize(event))
            for event in events
        ]

        with self.write_lock, self.conn:
            self.conn.executemany(
                'INSERT INTO state_events('
                '   identifier, source_statechange_id, block_number, data'
                ') VALUES(?, ?, ?, ?)',
                events_data,
            )

    def get_state_snapshot(self) -> Optional[Tuple[int, Any]]:
        """ Return the tuple of (last_applied_state_change_id, snapshot) or None"""
        cursor = self.conn.execute('SELECT statechange_id, data from state_snapshot')
        serialized = cursor.fetchall()

        result = None
        if serialized:
            assert len(serialized) == 1
            last_applied_state_change_id = serialized[0][0]
            snapshot_state = self.serializer.deserialize(serialized[0][1])
            return (last_applied_state_change_id, snapshot_state)

        return result

    def get_statechanges_by_identifier(self, from_identifier, to_identifier):
        if not (from_identifier == 'latest' or isinstance(from_identifier, int)):
            raise ValueError("from_identifier must be an integer or 'latest'")

        if not (to_identifier == 'latest' or isinstance(to_identifier, int)):
            raise ValueError("to_identifier must be an integer or 'latest'")

        cursor = self.conn.cursor()

        if from_identifier == 'latest':
            assert to_identifier is None

            cursor.execute(
                'SELECT identifier FROM state_changes ORDER BY identifier DESC LIMIT 1',
            )
            from_identifier = cursor.fetchone()

        if to_identifier == 'latest':
            cursor.execute(
                'SELECT data FROM state_changes WHERE identifier >= ?',
                (from_identifier,),
            )
        else:
            cursor.execute(
                'SELECT data FROM state_changes WHERE identifier '
                'BETWEEN ? AND ?', (from_identifier, to_identifier),
            )

        try:
            result = [
                self.serializer.deserialize(entry[0])
                for entry in cursor.fetchall()
            ]
        except AttributeError:
            raise InvalidDBData(
                'Your local database is corrupt. Bailing ...',
            )

        return result

    def get_events_by_identifier(self, from_identifier, to_identifier):
        if not (from_identifier == 'latest' or isinstance(from_identifier, int)):
            raise ValueError("from_identifier must be an integer or 'latest'")

        if not (to_identifier == 'latest' or isinstance(to_identifier, int)):
            raise ValueError("to_identifier must be an integer or 'latest'")

        cursor = self.conn.cursor()

        if from_identifier == 'latest':
            assert to_identifier is None

            cursor.execute(
                'SELECT identifier FROM state_events ORDER BY identifier DESC LIMIT 1',
            )
            from_identifier = cursor.fetchone()

        if to_identifier == 'latest':
            cursor.execute(
                'SELECT block_number, data FROM state_events WHERE identifier >= ?',
                (from_identifier,),
            )
        else:
            cursor.execute(
                'SELECT block_number, data FROM state_events WHERE identifier '
                'BETWEEN ? AND ?', (from_identifier, to_identifier),
            )

        result = [
            (entry[0], self.serializer.deserialize(entry[1]))
            for entry in cursor.fetchall()
        ]
        return result

    def get_events_by_block(self, from_block, to_block):
        if not (from_block == 'latest' or isinstance(from_block, int)):
            raise ValueError("from_block must be an integer or 'latest'")

        if not (to_block == 'latest' or isinstance(to_block, int)):
            raise ValueError("to_block must be an integer or 'latest'")

        cursor = self.conn.cursor()

        if from_block is None:
            from_block = 0

        if from_block == 'latest':
            assert to_block is None

            cursor.execute(
                'SELECT block_number FROM state_events ORDER BY block_number DESC LIMIT 1',
            )
            from_block = cursor.fetchone()

        if to_block == 'latest':
            cursor.execute(
                'SELECT block_number, data FROM state_events WHERE block_number >= ?',
                (from_block, ),
            )
        else:
            cursor.execute(
                'SELECT block_number, data FROM state_events WHERE block_number '
                'BETWEEN ? AND ?', (from_block, to_block),
            )

        result = [
            (entry[0], self.serializer.deserialize(entry[1]))
            for entry in cursor.fetchall()
        ]
        return result

    def __del__(self):
        self.conn.close()

###################demo

    def get_cross_state_change_by_identifier(self,identifier):
        cursor = self.conn.cursor()

        cursor.execute(
            'SELECT data FROM state_changes WHERE identifier = ?', (identifier,),
        )

        entry = cursor.fetchall()[0]

        res = self.serializer.deserialize(entry[0])

        #res = cursor.fetchall()[0]



        return res

    def create_crosstransaction(self, initiator_address, target_address, token_address, sendETH_amount, sendBTC_amount, receiveBTC_address, status,identifier):
        #identifier = encode_hex(privatekey_to_address(sha3(int(initiator_address,16) + int(target_address,16) + int(receiveBTC_address,16) + int(time.time()))))

        ###initiator_address = self.rest_api.raiden_api.raiden.default_registry.address
        ####ConnectionsInfoResource
        with self.write_lock, self.conn:
            self.conn.execute(
                'INSERT INTO crosstransaction_events(identifier, initiator_address, target_address, token_address, sendETH_amount, sendBTC_amount, receiveBTC_address, status, state_change_id, hash_r,r) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (identifier, initiator_address, target_address, token_address, sendETH_amount, sendBTC_amount, receiveBTC_address, status, 0, "", ""),
            )

        print(identifier)
        return  identifier


    def get_all_crosstransaction(self):
        cursor = self.conn.cursor()

        cursor.execute(
            'SELECT * FROM crosstransaction_events',
        )
        res_all = list()
        for res in cursor.fetchall():
            res = list(res)
            res[1] = to_normalized_address(res[1])
            res[2] = to_normalized_address(res[2])
            res[3] = to_normalized_address(res[3])
            res_all.append(res)
        return  res_all


    def get_crosstransaction_by_identifier(self,identifier):
        cursor = self.conn.cursor()

        cursor.execute(
            'SELECT * FROM crosstransaction_events WHERE identifier = ?', (identifier,),
        )

        res = cursor.fetchall()[0]



        return res


    def change_crosstransaction_status(self,identifier,status):

        entry = self.get_crosstransaction_by_identifier(identifier)

        with self.write_lock, self.conn:
            self.conn.execute(
                'INSERT OR REPLACE INTO crosstransaction_events('
                '    identifier,initiator_address, target_address, token_address, sendETH_amount, sendBTC_amount, receiveBTC_address, status, state_change_id, hash_r,r'
                ') VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (identifier, entry[1], entry[2], entry[3], entry[4], entry[5], entry[6], status, entry[8], entry[9], entry[10]),
            )

        print("success")


    def get_crosstransaction_by_r(self, hash_r):
        cursor = self.conn.cursor()

        cursor.execute(
            'SELECT * FROM crosstransaction_events WHERE hash_r = ?', (hash_r,),
        )

        res = cursor.fetchall()[0]



        return res


    def change_crosstransaction_statechangeid(self,identifier,id):

        entry = self.get_crosstransaction_by_identifier(identifier)

        with self.write_lock, self.conn:
            self.conn.execute(
                'INSERT OR REPLACE INTO crosstransaction_events('
                '    identifier,initiator_address, target_address, token_address, sendETH_amount, sendBTC_amount, receiveBTC_address, status, state_change_id, hash_r,r'
                ') VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (identifier, entry[1], entry[2], entry[3], entry[4], entry[5], entry[6], entry[7], id, entry[9], entry[10]),
            )

    def change_crosstransaction_r(self,identifier,r_hash, r):

        entry = self.get_crosstransaction_by_identifier(identifier)

        with self.write_lock, self.conn:
            self.conn.execute(
                'INSERT OR REPLACE INTO crosstransaction_events('
                '    identifier,initiator_address, target_address, token_address, sendETH_amount, sendBTC_amount, receiveBTC_address, status, state_change_id, hash_r,r'
                ') VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (identifier, entry[1], entry[2], entry[3], entry[4], entry[5], entry[6], entry[7], entry[8], r_hash, r),
            )