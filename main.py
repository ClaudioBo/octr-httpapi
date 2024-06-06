import os
import enet
import asyncio
import datetime
import traceback
import prometheus_logging
from dotenv import load_dotenv

from fastapi import FastAPI

tasks = []
room_info = {}
app = FastAPI()


@app.on_event("startup")
async def init_connection():
    global room_info, tasks
    room_info["servers"] = {}

    # Initialize room data
    load_dotenv(override=True)
    server_addresses = os.getenv("SERVER_LIST").split(",")

    # Start prometheus if found
    prom_task = asyncio.create_task(prometheus_logging.start_prometheus_server())
    prom_task.set_name("Prometheus server")
    tasks.append(prom_task)

    # Assign a task each address
    for address in server_addresses:
        room_info["servers"][address] = None
        prometheus_logging.add_server(address)
        prometheus_logging.set_player_count_server(address, 0)
        task = asyncio.create_task(connect_server(address))
        task.set_name(address)
        tasks.append(task)


@app.on_event("shutdown")
async def shutdown_event():
    for task in tasks:
        print(f"Stopping task for '{task.get_name()}'")
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def connect_server(address):
    global room_info

    RECONNECTION_SECONDS = 30
    RECONNECTION_ATTEMPTS_BEFORE_CLEAN = 10

    # Define UDP server details
    ipaddr, port = address.split(":")
    port = int(port)
    message = b"Hello"  # empty

    was_exception = True
    reconnection_attempts = 0

    while True:
        try:
            # Create an ENET host for the client
            if was_exception:
                print(f"[{address}] Reconnecting...")
            client = enet.Host(None, 1, 2, 0, 0)

            # Connect to the ENET server
            peer = client.connect(enet.Address(ipaddr.encode(), port), 3000)

            # Loop to receive data from server
            while True:
                try:
                    event = client.service(3000)
                    if event.type == enet.EVENT_TYPE_CONNECT:
                        if was_exception:
                            print(f"[{address}] Reconnected")
                            was_exception = False
                            reconnection_attempts = 0
                    elif event.type == enet.EVENT_TYPE_RECEIVE:
                        data = parse_message_rooms(address, event.packet.data)
                        if not data is None:
                            room_info["servers"][address] = data
                        # print(f"[{address}] Received data: {data} ({event.packet.data})")
                        peer.disconnect()
                    elif event.type == enet.EVENT_TYPE_DISCONNECT:
                        # print(f"[{address}] Disconnected")
                        break
                    await asyncio.sleep(0.1)
                except Exception:
                    was_exception = True
                    print(f"[{address}] An error occurred, reconnecting in 10s:")
                    traceback.print_exc()
                    prometheus_logging.set_player_count_server(address, 0)
                    asyncio.sleep(RECONNECTION_SECONDS)
                await asyncio.sleep(RECONNECTION_SECONDS)
        except Exception:
            if was_exception:
                reconnection_attempts += 1
                if reconnection_attempts > RECONNECTION_ATTEMPTS_BEFORE_CLEAN:
                    room_info["servers"][address] = None
            was_exception = True
            print(f"[{address}] An error occurred, reconnecting in 10s:")
            traceback.print_exc()
            prometheus_logging.set_player_count_server(address, 0)
            asyncio.sleep(RECONNECTION_SECONDS)


def parse_message_rooms(address, packet_data):
    parsed_data = {}

    # Parse type, size, and numRooms
    type_size_numRooms = packet_data[0]
    type = type_size_numRooms >> 4

    if not type == 12:
        return None

    # packet_size = type_size_numRooms & 0x0F
    # num_rooms = packet_data[1]

    # Parse version
    parsed_data["version"] = int.from_bytes(packet_data[2:4], byteorder="little")

    # Parse numClients for each room
    total_players = 0
    parsed_data["total_players"] = total_players
    parsed_data["max_players"] = type_size_numRooms
    parsed_data["last_fetched"] = datetime.datetime.now().isoformat()
    parsed_data["room"] = []
    temp_rooms = []
    for i in range(4, len(packet_data)):
        num_clients_high = packet_data[i] >> 4
        num_clients_low = packet_data[i] & 0x0F
        temp_rooms.append(num_clients_high)
        temp_rooms.append(num_clients_low)

    # Correctly format player count
    for i, temp in enumerate(temp_rooms):
        is_room_locked = temp > 8
        current_players = temp - 8 if is_room_locked else temp
        parsed_data["room"].append(
            {
                "room_name": str(i),
                "players": current_players,
                "room_locked": is_room_locked,
            }
        )
        total_players += current_players
    parsed_data["total_players"] = total_players
    prometheus_logging.set_player_count_server(address, total_players)

    return parsed_data


@app.get("/")
async def rooms():
    return room_info
