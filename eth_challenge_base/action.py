import json
import os
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, List

import pyseto
from eth_typing import ChecksumAddress, HexStr
from eth_utils import to_checksum_address
from web3.exceptions import TransactionNotFound

from eth_challenge_base.config import Config, Constructor
from eth_challenge_base.utils import Account, Contract, web3


@dataclass
class Action:
    description: str
    handler: Callable[[], int]


class Actions:
    def __init__(self, challenge_dir: str, config: Config) -> None:
        with open(
            os.path.join(challenge_dir, "build", "contracts", f"{config.contract}.json")
        ) as fp:
            build_json = json.load(fp)
        self._contract: Contract = Contract(build_json)
        self._token_key = pyseto.Key.new(
            version=4, purpose="local", key=os.getenv("TOKEN_SECRET", "")
        )

        self._actions: List[Action] = []
        if not config.deployed_addr:
            self._actions = [
                self._create_account_action(config.constructor),
                self._deploy_contract_action(config.constructor),
            ]
        self._actions.append(
            self._get_flag_action(
                config.flag, config.solved_event, config.deployed_addr
            )
        )
        if config.show_source:
            self._actions.append(
                self._show_source_action(os.path.join(challenge_dir, "contracts"))
            )

    def __getitem__(self, index: int) -> Action:
        return self._actions[index]

    def __len__(self):
        return len(self._actions)

    def _create_account_action(self, constructor: Constructor) -> Action:
        def action() -> int:
            account: Account = Account()
            print(f"[+] deployer account: {account.address}")
            token: str = pyseto.encode(
                self._token_key, payload=account.private_key
            ).decode("utf-8")
            print(f"[+] token: {token}")

            gas_limit: int = (
                constructor.gas_limit
                or self._contract.deploy.estimate_gas(constructor.args)
            )
            total_value: Decimal = web3.fromWei(
                constructor.value + gas_limit * web3.eth.gas_price, "ether"
            )
            print(
                f"[+] please transfer {(total_value+Decimal('0.000005')).quantize(Decimal('0.00000'))} test ether to the deployer account for next step"
            )

            return 0

        return Action(
            description="Create an account which will be used to deploy the challenge contract",
            handler=action,
        )

    def _deploy_contract_action(self, constructor: Constructor) -> Action:
        def action() -> int:
            try:
                private_key: str = pyseto.decode(
                    self._token_key, input("[-] input your token: ").strip()
                ).payload.decode("utf-8")
            except Exception as e:
                print(e)
                return 1

            account: Account = Account(private_key)
            if account.balance() == 0:
                print(
                    f"[+] don't forget to get some test ether for {account.address} first"
                )
                return 1

            contract_addr: str = account.get_deployment_address()
            try:
                tx_hash: str = self._contract.deploy(
                    account, constructor.value, constructor.args, constructor.gas_limit
                )
            except Exception as e:
                print(e)
                return 1
            print(f"[+] contract address: {contract_addr}")
            print(f"[+] transaction hash: {tx_hash}")
            return 0

        return Action(
            description="Deploy the challenge contract using your generated account",
            handler=action,
        )

    def _get_flag_action(
        self, flag: str, solved_event: str, deployed_addr: str
    ) -> Action:
        def action() -> int:
            if not deployed_addr:
                try:
                    private_key: str = pyseto.decode(
                        self._token_key, input("[-] input your token: ").strip()
                    ).payload.decode("utf-8")
                except ValueError as e:
                    print(e)
                    return 1

                account: Account = Account(private_key)
                nonce: int = account.nonce
                if nonce == 0:
                    print("[+] challenge contract has not yet been deployed")
                    return 1
                contract_addr: ChecksumAddress = account.get_deployment_address(
                    nonce - 1
                )
            else:
                contract_addr: ChecksumAddress = to_checksum_address(deployed_addr)

            is_solved = False
            if solved_event:
                tx_hash = input(
                    f"[-] input tx hash that emitted {solved_event} event: "
                ).strip()
                try:
                    logs = self._contract.get_events(solved_event, HexStr(tx_hash))
                except TransactionNotFound as e:
                    print(e)
                    return 1

                for item in logs:
                    if item["address"] == contract_addr:
                        is_solved = True
            else:
                is_solved = self._contract.at(contract_addr).isSolved().call()

            if is_solved:
                print(f"[+] flag: {flag}")
                return 0
            else:
                print("[+] it seems that you have not solved the challenge~~~~")
                return 1

        return Action(
            description="Get your flag once you meet the requirement", handler=action
        )

    def _show_source_action(self, contract_dir: str) -> Action:
        def action() -> int:
            for file in os.listdir(contract_dir):
                if re.match(".*\.(sol|vy)$", file):  # noqa: W605
                    with open(os.path.join(contract_dir, file)) as fp:
                        print()
                        print(file)
                        print(fp.read())

            return 0

        return Action(description="Show the contract source code", handler=action)
