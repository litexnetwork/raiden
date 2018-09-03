DB_CREATE_SETTINGS = '''
CREATE TABLE IF NOT EXISTS settings (
    name VARCHAR[24] NOT NULL PRIMARY KEY,
    value TEXT
);
'''

DB_CREATE_STATE_CHANGES = '''
CREATE TABLE IF NOT EXISTS state_changes (
    identifier INTEGER PRIMARY KEY AUTOINCREMENT,
    data BINARY
);
'''

DB_CREATE_SNAPSHOT = '''
CREATE TABLE IF NOT EXISTS state_snapshot (
    identifier INTEGER PRIMARY KEY,
    statechange_id INTEGER,
    data BINARY,
    FOREIGN KEY(statechange_id) REFERENCES state_changes(identifier)
);
'''

DB_CREATE_STATE_EVENTS = '''
CREATE TABLE IF NOT EXISTS state_events (
    identifier INTEGER PRIMARY KEY,
    source_statechange_id INTEGER NOT NULL,
    block_number INTEGER NOT NULL,
    data BINARY,
    FOREIGN KEY(source_statechange_id) REFERENCES state_changes(identifier)
);
'''

DB_CREATE_CROSSTRANSACTION_EVENTS = '''
CREATE TABLE IF NOT EXISTS crosstransaction_events (
    identifier INTEGER PRIMARY KEY, 
    initiator_address VARCHAR, 
    target_address VARCHAR, 
    token_address VARCHAR, 
    sendETH_amount INTEGER NOT NULL, 
    sendBTC_amount INTEGER NOT NULL, 
    receiveBTC_address VARCHAR, 
    status INTEGER NOT NULL,
    state_change_id INTEGER,
    hash_r VARCHAR,
    r VARCHAR
);
'''

DB_CREATE_LND = '''
CREATE TABLE IF NOT EXISTS lnd (
    identifier INTEGER PRIMARY KEY,
    port VARCHAR,
    identity VARCHAR,
    address VARCHAR,
    macaroon VARCHAR
);
'''

DB_SCRIPT_CREATE_TABLES = """
PRAGMA foreign_keys=off;
BEGIN TRANSACTION;
{}{}{}{}{}{}
COMMIT;
PRAGMA foreign_keys=on;
""".format(
    DB_CREATE_SETTINGS,
    DB_CREATE_STATE_CHANGES,
    DB_CREATE_SNAPSHOT,
    DB_CREATE_STATE_EVENTS,
    DB_CREATE_CROSSTRANSACTION_EVENTS,
    DB_CREATE_LND,
)
