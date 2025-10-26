import random

from flask import request
from flask_socketio import join_room, emit

from config import socketio

rooms = []
room_size = 4
next_room_id = 1

@socketio.on('connect')
def connect():
    global  next_room_id
    sid = request.sid
    name = request.args.get('player_name')
    print(f'Client connected: {name} ({sid})')

    room = None
    for r in rooms:
        if len(r["players"]) < room_size and r["state"] == "matchmaking":
            r["players"].append({"sid": sid, "name": name})
            room = r
            break

    if room is None:
        room_id = next_room_id
        next_room_id += 1
        room = {"id": room_id, "state": "matchmaking", "players": [{"sid": sid, "name": name}]}
        rooms.append(room)

    room_id = room["id"]
    join_room(str(room_id))

    emit(
        'room_players',
        {"room_id": room_id, "players": [p["name"] for p in room["players"]]},
        to=str(room_id)
    )

    print(rooms)

    if len(room["players"]) == room_size and room["state"] == "matchmaking":
        print(f"Room {room_id} is full. Starting game!")

        for i, p in enumerate(room["players"]):
            p["id"] = i
            emit('player_index', i, to=p["sid"])

        suits = ["C", "D", "H", "S"]
        ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]

        cards = []

        for suit in suits:
            for rank in ranks:
                cards.append(f"{rank}{suit}")

        random.shuffle(cards)
        room["cards"] = cards

        for p in room["players"]:
            lst = []

            for j in range(4):
                lst.append(cards.pop())

            p["cards"] = lst

        player_turn = random.randint(0, 3)
        turn_type = "draw"

        room["player_turn"] = player_turn
        room["player_first_turn"] = player_turn
        room["discarded"] = []
        room["turn_type"] = turn_type
        room["state"] = "playing"

        players = [{"id": p["id"], "name": p["name"], "cards": p["cards"]} for p in room["players"]]
        emit(
            'start_game',
            {"players": players, "cards": cards, "player_turn": player_turn, "turn_type": turn_type},
            to=str(room_id))

@socketio.on('disconnect')
def disconnect():
    sid = request.sid
    print(f"Client disconnected ({sid})")

    for room in rooms:
        for player in room["players"]:
            if player["sid"] == sid:
                room["players"].remove(player)

                if room["state"] == "playing":
                    players_turn_that_disconnected = False

                    if player["id"] == room["player_turn"]:
                        room["turn_type"] = "draw"

                        players_turn_that_disconnected = True

                        while True:

                            room["player_turn"] = (room["player_turn"] + 1) % 4

                            if room["player_turn"] in [p["id"] for p in room["players"]]:
                                break

                    emit(
                        'disconnect_on_game',
                        {"room_id": room["id"], "player_id": player["id"],
                         "player_turn": room["player_turn"], "turn_type": room["turn_type"],
                         "players_turn_that_disconnected": players_turn_that_disconnected},
                        to=str(room["id"])
                    )

                    if len(room["players"]) == 1:
                        room["state"] = "finished"

                        result = {
                            "id": room["players"][0]["id"],
                            "name": room["players"][0]["name"],
                            "score": get_best_suit_score(convert_to_dict(room["players"][0]["cards"]))
                        }

                        emit(
                            'one_player_win',
                            {"winner": room["players"][0]["id"],
                             "result": [result]},
                            to=str(room["id"])
                        )

                if room["state"] == "matchmaking":
                    emit(
                        'room_players',
                        {"room_id": room["id"], "players": [p["name"] for p in room["players"]]},
                        to=str(room["id"])
                    )

                if not room["players"]:
                    rooms.remove(room)

                return

@socketio.on('draw_card')
def draw_card(data):
    sid = request.sid
    action = data["action"]
    player_id = data["player_id"]

    for room in rooms:
        for player in room["players"]:
            if player["sid"] == sid and room["player_turn"] == player["id"] and player["id"] == player_id:

                if not room["discarded"]:
                    action = "draw_from_deck"

                if action == "draw_discarded":
                    discarded = room["discarded"].pop()
                    player["cards"].append(discarded)

                if action == "draw_from_deck":
                    card = room["cards"].pop()
                    player["cards"].append(card)

                room["turn_type"] = "discard"

                emit(
                    'after_draw_card',
                    {"turn_type": room["turn_type"], "action": action, "player_turn": room["player_turn"], "player_id": player_id},
                    to=str(room["id"])
                )

                return

@socketio.on('discard_card')
def discard_card(data):
    sid = request.sid
    card_to_discard = data["card"]
    player_id = data["player_id"]

    for room in rooms:
        for player in room["players"]:
            if player["sid"] == sid and room["player_turn"] == player["id"] and player["id"] == player_id:

                player["cards"].remove(card_to_discard)

                if room["discarded"]:
                    room["discarded"].clear()

                room["discarded"].append(card_to_discard)

                best_score = get_best_suit_score(convert_to_dict(player["cards"]))

                if best_score >= 41:
                    scores = []

                    room["state"] = "finished"

                    for p in room["players"]:
                        score = get_best_suit_score(convert_to_dict(p["cards"]))

                        scores.append({"score": score, "id": p["id"], "name": p["name"]})

                    emit(
                        'win',
                        {"card": card_to_discard, "player_id": player_id, "winner": player_id, "result": scores},
                        to=str(room["id"])
                    )
                else:
                    if not room["cards"]:
                        highest_score = 0
                        scores = []

                        room["state"] = "finished"

                        for p in room["players"]:
                            score = get_best_suit_score(convert_to_dict(p["cards"]))

                            scores.append({"score": score, "id": p["id"], "name": p["name"]})
                            highest_score = max(score, highest_score)

                        winners = [s["id"] for s in scores if s["score"] == highest_score]
                        winner = winners[-1]

                        for i in range(room["player_first_turn"], room["player_first_turn"] + 4):
                            if (i % 4) in winners:
                                winner = i % 4
                                break

                        emit(
                            'win',
                            {"card": card_to_discard, "player_id": player_id, "winner": winner, "result": scores},
                            to=str(room["id"])
                        )
                    else:
                        room["turn_type"] = "draw"

                        while True:

                            room["player_turn"] = (room["player_turn"] + 1) % 4

                            if room["player_turn"] in [p["id"] for p in room["players"]]:
                                break

                        emit(
                            'after_discard_card',
                            {"turn_type": room["turn_type"], "card": card_to_discard,
                             "player_turn": room["player_turn"], "player_id": player_id},
                            to=str(room["id"])
                        )

                return

def get_best_suit_score(hand):
    from itertools import groupby

    # Sort the hand by suit so groupby works correctly
    hand.sort(key=lambda c: c["suit"])

    max_score = 0
    for suit, group in groupby(hand, key=lambda c: c["suit"]):
        total_value = sum(c["value"] for c in group)
        max_score = max(max_score, total_value)

    return max_score

def get_card_value(rank):
    dct = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10, "J": 10, "Q": 10, "K": 10, "A": 11}

    return dct[rank]

def convert_to_dict(cards):
    return [{"suit": c[-1], "value": get_card_value(c[0:-1])} for c in cards]