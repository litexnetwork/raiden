import structlog
import random

from eth_utils import to_normalized_address, encode_hex

from raiden.raiden_service import RaidenService
from raiden.utils import random_secret
from raiden.routing import get_best_routes
from raiden.transfer import views
from raiden.transfer.state import balanceproof_from_envelope
from raiden.transfer.state_change import (
    ReceiveProcessed,
    ReceiveTransferDirect,
    ReceiveUnlock,
    ReceiveCrosstransaction)
from raiden.messages import (
    DirectTransfer,
    LockedTransfer,
    Message,
    Processed,
    RefundTransfer,
    RevealSecret,
    Secret,
    SecretRequest,
    Crosstransaction,
    AcceptCross,
    CrossLockedTransfer,
    CrossSecretRequest,
)
from raiden.transfer.mediated_transfer.state import lockedtransfersigned_from_message
from raiden.transfer.mediated_transfer.state_change import (
    ReceiveSecretRequest,
    ReceiveSecretReveal,
    ReceiveTransferRefund,
    ReceiveTransferRefundCancelRoute,
)
from raiden.constants import (
    UINT256_MAX,
    UINT64_MAX,
)
from eth_utils import encode_hex

log = structlog.get_logger(__name__)  # pylint: disable=invalid-name


def handle_message_secretrequest(raiden: RaidenService, message: SecretRequest):
    secret_request = ReceiveSecretRequest(
        message.payment_identifier,
        message.amount,
        message.secrethash,
        message.sender,
    )
    raiden.handle_state_change(secret_request)


def handle_message_revealsecret(raiden: RaidenService, message: RevealSecret):
    state_change = ReceiveSecretReveal(
        message.secret,
        message.sender,
    )
    raiden.handle_state_change(state_change)


def handle_message_secret(raiden: RaidenService, message: Secret):
    balance_proof = balanceproof_from_envelope(message)
    state_change = ReceiveUnlock(
        message_identifier=message.message_identifier,
        secret=message.secret,
        balance_proof=balance_proof,
    )
    raiden.handle_state_change(state_change)


def handle_message_refundtransfer(raiden: RaidenService, message: RefundTransfer):
    token_network_address = message.token_network_address
    from_transfer = lockedtransfersigned_from_message(message)
    chain_state = views.state_from_raiden(raiden)

    routes = get_best_routes(
        chain_state,
        token_network_address,
        raiden.address,
        from_transfer.target,
        from_transfer.lock.amount,
        message.sender,
    )

    role = views.get_transfer_role(
        chain_state,
        from_transfer.lock.secrethash,
    )

    if role == 'initiator':
        secret = random_secret()
        state_change = ReceiveTransferRefundCancelRoute(
            message.sender,
            routes,
            from_transfer,
            secret,
        )
    else:
        state_change = ReceiveTransferRefund(
            message.sender,
            from_transfer,
            routes,
        )

    raiden.handle_state_change(state_change)


def handle_message_directtransfer(raiden: RaidenService, message: DirectTransfer):
    token_network_identifier = message.token_network_address
    balance_proof = balanceproof_from_envelope(message)

    direct_transfer = ReceiveTransferDirect(
        token_network_identifier,
        message.message_identifier,
        message.payment_identifier,
        balance_proof,
    )

    raiden.handle_state_change(direct_transfer)


def handle_message_lockedtransfer(raiden: RaidenService, message: LockedTransfer):
    if message.target == raiden.address:
        raiden.target_mediated_transfer(message)
    else:
        raiden.mediate_mediated_transfer(message)


def handle_message_processed(raiden: RaidenService, message: Processed):
    processed = ReceiveProcessed(message.message_identifier)
    raiden.handle_state_change(processed)

def handle_message_crosstransaction(raiden: RaidenService, message : Crosstransaction):
    cross_type = message.cross_type
    if cross_type==1:
        raiden.wal.create_crosstransactiontry(message.initiator_address, message.target_address, message.token_network_identifier, message.sendETH_amount, message.sendBTC_amount, message.receiveBTC_address,message.identifier)
        raiden.wal.change_crosstransaction_status(message.identifier, 2)
        accept=1
        acceptcross = AcceptCross(random.randint(0, UINT64_MAX),message.initiator_address,message.target_address,message.identifier,accept)
        raiden.sign(acceptcross)
        raiden.transport.send_async(
            message.initiator_address,
            bytes("123", 'utf-8'),
            acceptcross,
        )
    else:
        message.cross_type = 1
        async_result = raiden.start_crosstransaction(message.token_network_identifier,message.initiator_address,message.target_address,message.sendETH_amount,message.sendBTC_amount,message.receiveBTC_address,message.cross_type,message.identifier)

        # return async_result.wait(timeout=None)

        # if message.cross_type == 0:
        #     accept=8
        #     acceptcross = AcceptCross(random.randint(0, UINT64_MAX),message.initiator_address,message.target_address,message.identifier,accept)
        
        #     raiden.sign(acceptcross)
        #     print("async result done, send message to A")
        #     print(to_normalized_address(message.initiator_address))
        #     raiden.transport.send_async(
        #         message.initiator_address,
        #         bytes("123", 'utf-8'),
        #         acceptcross,
        #     )
        
    



def handle_message_acceptcross(raiden:RaidenService,message:AcceptCross):
    # for sync
    if message.accept == 7:
        raiden.wal.change_crosstransaction_status(message.identifier, 8)
        log.info('##sync received')
        return


    raiden.wal.change_crosstransaction_status(message.identifier, 3)
    raiden.start_send_crosstansfer(message.identifier)


def handle_message_crosslockedtransfer(raiden:RaidenService,message:CrossLockedTransfer):
    locked_transfer_message = LockedTransfer(
        message.chain_id,
        message.message_identifier,
        message.payment_identifier,
        message.nonce,
        message.token_network_address,
        message.token,
        message.channel,
        message.transferred_amount,
        message.locked_amount,
        message.recipient,
        message.locksroot,
        message. lock,
        message.target,
        message.initiator,
        message.fee
    )
    #locked_transfer_message.sender = message.sender
    locked_transfer_message.signature = message.locked_transfer_signature
    if message.target == raiden.address:
        raiden.cross_handle_recieved_locked_transfer(locked_transfer_message, message.cross_id)

        raiden.wal.change_crosstransaction_status(message.cross_id, 4)
        raiden.wal.storage.change_crosstransaction_r(message.cross_id, encode_hex(locked_transfer_message.lock.secrethash), "")

        #to do send lnd string to lnd
        lnd_string = message.lnd_string.decode('utf-8')
        raiden.send_payment_request(lnd_string)
    else:
        handle_message_lockedtransfer(raiden, locked_transfer_message)




def handle_message_crosssecretrequest(raiden, message):
    secret_request_message = SecretRequest(
        message.message_identifier,
        message.payment_identifier,
        message.secrethash,
        message.amount
    )

    secret_request_message.signature = message.secret_request_signature

    state_change = ReceiveSecretRequest(
        secret_request_message.payment_identifier,
        secret_request_message.amount,
        secret_request_message.secrethash,
        secret_request_message.sender,
    )

    row = raiden.wal.get_crosstransaction_by_identifier(message.cross_id)
    if row[7] == 6:
        raiden.handle_state_change(state_change)
        raiden.wal.change_crosstransaction_status(message.cross_id, 8)
        #sync
        acceptcross = AcceptCross(random.randint(0, UINT64_MAX),row[1],row[2],message.cross_id,7)
        raiden.sign(acceptcross)
        raiden.transport.send_async(
            row[2],
            bytes("123", 'utf-8'),
            acceptcross,
        )
        log.info('##sync sended')
    else:
        raiden.wal.change_crosstransaction_status(message.cross_id, 5)
        state_change_id = raiden.wal.storage.write_state_change(state_change)
        raiden.wal.storage.change_crosstransaction_statechangeid(message.cross_id, state_change_id)




def on_message(raiden: RaidenService, message: Message):
    """ Return True if the message is known. """
    # pylint: disable=unidiomatic-typecheck
    if type(message) == SecretRequest:
        handle_message_secretrequest(raiden, message)
    elif type(message) == RevealSecret:
        handle_message_revealsecret(raiden, message)
    elif type(message) == Secret:
        handle_message_secret(raiden, message)
    elif type(message) == DirectTransfer:
        handle_message_directtransfer(raiden, message)
    elif type(message) == RefundTransfer:
        handle_message_refundtransfer(raiden, message)
    elif type(message) == LockedTransfer:
        handle_message_lockedtransfer(raiden, message)
    elif type(message) == Processed:
        handle_message_processed(raiden, message)
    elif type(message) == Crosstransaction:
        handle_message_crosstransaction(raiden,message)
    elif type(message) == AcceptCross:
        handle_message_acceptcross(raiden,message)
    elif type(message) == CrossLockedTransfer:
        handle_message_crosslockedtransfer(raiden, message)
    elif type(message) == CrossSecretRequest:
        handle_message_crosssecretrequest(raiden, message)
    else:
        log.error('Unknown message cmdid {}'.format(message.cmdid))
        return False

    # Inform the transport that it's okay to send a Delivered message
    return True
