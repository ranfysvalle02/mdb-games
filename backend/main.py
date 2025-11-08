# backend/main.py
import uvicorn
import motor.motor_asyncio
import random
import string
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# --- Import Game Engines ---
import domino_logic
import blackjack_logic

# --- The "Router" Dictionary ---
GAME_LOGIC_MODULES = {
    "dominoes": domino_logic,
    "blackjack": blackjack_logic,
}

# --- App Setup ---
app = FastAPI()
MONGO_DETAILS = "mongodb://localhost:27017/?retryWrites=true&w=majority&directConnection=true" # Assumes MongoDB is running
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_DETAILS)
db = client.game_portal_db
games_collection = db.get_collection("games")

# --- Connection Manager ---
class ConnectionManager:
    def __init__(self):
        # { "game_id": { "player_id": WebSocket } }
        self.active_connections: dict[str, dict[str, WebSocket]] = {}

    async def connect(self, websocket: WebSocket, game_id: str, player_id: str):
        await websocket.accept()
        if game_id not in self.active_connections:
            self.active_connections[game_id] = {}
        self.active_connections[game_id][player_id] = websocket

    def disconnect(self, game_id: str, player_id: str):
        if game_id in self.active_connections and player_id in self.active_connections[game_id]:
            del self.active_connections[game_id][player_id]

    async def broadcast_to_game(self, game_id: str, message: dict):
        if game_id in self.active_connections:
            for player_id, connection in self.active_connections[game_id].items():
                try:
                    await connection.send_json(message)
                except Exception as e:
                    print(f"Error sending to {player_id}: {e}")

    async def send_to_player(self, game_id: str, player_id: str, message: dict):
        if game_id in self.active_connections and player_id in self.active_connections[game_id]:
            try:
                await self.active_connections[game_id][player_id].send_json(message)
            except Exception as e:
                print(f"Error sending to {player_id}: {e}")
                
manager = ConnectionManager()

# --- Utility Functions ---
def generate_game_id(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def generate_player_id(length=10):
    return "p_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def generate_ai_player_name():
    """Generates a random AI player name."""
    ai_names = ["Bot Alpha", "Bot Beta", "Bot Gamma", "Bot Delta", "AI Player", "Computer", "AutoBot"]
    return random.choice(ai_names)

def get_ai_players_needed(game_type: str, current_player_count: int) -> int:
    """
    Determines how many AI players are needed to fill the game to optimal capacity.
    Returns the number of AI players to add.
    """
    if game_type == "dominoes":
        # Dominoes needs 2-4 players, fill to 4 for optimal gameplay
        max_players = 4
        if current_player_count < max_players:
            return max_players - current_player_count
        return 0
    elif game_type == "blackjack":
        # Blackjack works well with 3-4 players total
        optimal_players = 4
        if current_player_count < optimal_players:
            return optimal_players - current_player_count
        return 0
    return 0

def is_ai_player(game_id: str, player_id: str) -> bool:
    """Checks if a player is an AI player (no WebSocket connection)."""
    if game_id not in manager.active_connections:
        return True
    return player_id not in manager.active_connections[game_id]

def make_ai_move_blackjack(game_state: dict, player_id: str) -> dict:
    """Simple AI for blackjack: hit if value < 17, otherwise stand."""
    player_state = game_state['hands'][player_id]
    if player_state['status'] != 'playing':
        return game_state
    
    if player_state['value'] < 17:
        move_data = {"action": "hit"}
    else:
        move_data = {"action": "stand"}
    
    return blackjack_logic.play_move(game_state, player_id, move_data)

def make_ai_move_dominoes(game_state: dict, player_id: str) -> dict:
    """Simple AI for dominoes: play first valid tile, or draw if none, or pass."""
    hand = game_state['hands'][player_id]
    board = game_state['board']
    
    if not board:
        # First move: play highest tile
        if hand:
            highest_tile = max(hand, key=lambda t: sum(t))
            move_data = {"action": "play", "tile": list(highest_tile), "side": "right"}
            return domino_logic.play_move(game_state, player_id, move_data)
    else:
        # Find a playable tile
        left_end, right_end = domino_logic.get_open_ends(board)
        for tile in hand:
            if tile[0] == left_end or tile[1] == left_end:
                move_data = {"action": "play", "tile": list(tile), "side": "left"}
                return domino_logic.play_move(game_state, player_id, move_data)
            elif tile[0] == right_end or tile[1] == right_end:
                move_data = {"action": "play", "tile": list(tile), "side": "right"}
                return domino_logic.play_move(game_state, player_id, move_data)
        
        # No playable tile: draw if possible, otherwise pass
        if game_state['boneyard']:
            move_data = {"action": "draw"}
            return domino_logic.play_move(game_state, player_id, move_data)
        else:
            move_data = {"action": "pass"}
            return domino_logic.play_move(game_state, player_id, move_data)
    
    # Fallback: pass
    move_data = {"action": "pass"}
    return domino_logic.play_move(game_state, player_id, move_data)

def sanitize_game_state_for_player(game_type: str, game_state: dict, player_id: str):
    """
    Hides sensitive info (other hands, boneyard, dealer card) before sending.
    """
    if not game_state:
        return None

    # Use json library to create a deep copy to avoid modifying the original
    sanitized_state = json.loads(json.dumps(game_state))
    
    # --- Generic Sanitization ---
    if 'hands' in sanitized_state:
        for pid, hand_data in sanitized_state['hands'].items():
            if pid != player_id:
                if game_type == 'dominoes':
                    sanitized_state['hands'][pid] = f"{len(hand_data)} tiles"
                elif game_type == 'blackjack':
                    # Hide hand, but keep status
                    sanitized_state['hands'][pid]['hand'] = f"{len(hand_data['hand'])} cards"

    if 'boneyard' in sanitized_state: # Dominoes
        # Preserve count for current player (they need to know if they can draw)
        if isinstance(sanitized_state['boneyard'], list):
            sanitized_state['boneyard_count'] = len(sanitized_state['boneyard'])
        sanitized_state['boneyard'] = f"{len(sanitized_state['boneyard']) if isinstance(sanitized_state['boneyard'], list) else 0} tiles"
    if 'deck' in sanitized_state: # Blackjack
        sanitized_state['deck'] = f"{len(sanitized_state['deck'])} cards"

    # --- Game-Specific Sanitization ---
    if game_type == 'blackjack' and sanitized_state['status'] == 'in_progress':
        # Hide dealer's hole card
        first_card = sanitized_state['dealer_hand'][0]
        sanitized_state['dealer_hand'] = [first_card, {"rank": "?", "suit": ""}]
        # Show only the value of the up-card
        sanitized_state['dealer_value'] = first_card['value']
        if first_card['rank'] == 'A': sanitized_state['dealer_value'] = 11
    
    return sanitized_state

# --- HTTP API Models ---
class CreateGameRequest(BaseModel):
    player_id: str = Field(..., min_length=1, max_length=200)
    game_type: str = Field(..., description="e.g., 'dominoes' or 'blackjack'")
    game_mode: str = Field(default="classic", description="For dominoes: 'classic' or 'boricua'. For blackjack: 'best_of_5' or 'best_of_10'")

class JoinGameRequest(BaseModel):
    player_id: str = Field(..., min_length=1, max_length=200)

# --- HTTP API Endpoints (Lobby) ---
@app.post("/api/game/create")
async def create_game(request: CreateGameRequest):
    """Creates a new game lobby."""
    if request.game_type not in GAME_LOGIC_MODULES:
        raise HTTPException(status_code=400, detail="Invalid game type.")
        
    game_id = generate_game_id()
    player_id = request.player_id  # Use fingerprint as player_id
    
    game_document = {
        "_id": game_id,
        "game_type": request.game_type,
        "game_mode": request.game_mode if request.game_type == "dominoes" else None,
        "host_id": player_id,
        "players": [
            {"player_id": player_id}
        ],
        "status": "waiting",
        "game_state": None
    }
    await games_collection.insert_one(game_document)
    
    return {"game_id": game_id, "player_id": player_id}

@app.post("/api/game/{game_id}/join")
async def join_game(game_id: str, request: JoinGameRequest):
    """Allows a new player to join a waiting game."""
    game = await games_collection.find_one({"_id": game_id})
    if not game:
        raise HTTPException(status_code=404, detail="Game not found.")
    if game['status'] != 'waiting':
        raise HTTPException(status_code=400, detail="Game has already started.")
    if len(game['players']) >= 4:
        raise HTTPException(status_code=400, detail="Game is full.")

    player_id = request.player_id  # Use fingerprint as player_id
    
    # Check if player already in game
    existing_player = next((p for p in game.get('players', []) if p.get('player_id') == player_id), None)
    if existing_player:
        return {"game_id": game_id, "player_id": player_id}
    
    new_player = {"player_id": player_id}
    
    await games_collection.update_one(
        {"_id": game_id},
        {"$push": {"players": new_player}}
    )
    
    # Notify lobby (via WebSocket) that someone joined
    await manager.broadcast_to_game(game_id, {
        "type": "player_joined",
        "player_id": player_id
    })
    
    return {"game_id": game_id, "player_id": player_id}

async def process_ai_moves(game_id: str, game_type: str, game_state: dict):
    """Processes AI moves until it's a human player's turn or the game ends."""
    max_iterations = 20  # Safety limit to prevent infinite loops
    iteration = 0
    
    while game_state['status'] == 'in_progress' and iteration < max_iterations:
        iteration += 1
        
        # Get current player
        current_turn_index = game_state.get('current_turn_index', 0)
        if current_turn_index >= len(game_state['players']):
            break
        
        current_player_id = game_state['players'][current_turn_index]
        
        # Check if current player is AI
        if not is_ai_player(game_id, current_player_id):
            break  # It's a human player's turn, stop processing
        
        # Make AI move
        try:
            if game_type == 'blackjack':
                game_state = make_ai_move_blackjack(game_state, current_player_id)
            elif game_type == 'dominoes':
                game_state = make_ai_move_dominoes(game_state, current_player_id)
            else:
                break
            
            # Update game state in database
            await games_collection.update_one(
                {"_id": game_id},
                {"$set": {"game_state": game_state}}
            )
            
            # Broadcast updated state to all players
            for pid in game_state['players']:
                sanitized = sanitize_game_state_for_player(game_type, game_state, pid)
                await manager.send_to_player(game_id, pid, {
                    "type": "state_update",
                    "game_state": sanitized
                })
            
            # Small delay to make AI moves visible
            await asyncio.sleep(0.5)
            
        except Exception as e:
            print(f"Error processing AI move for {current_player_id}: {e}")
            break

# --- WebSocket Endpoint (Main Game) ---
@app.websocket("/ws/game/{game_id}/{player_id}")
async def websocket_endpoint(websocket: WebSocket, game_id: str, player_id: str):
    
    # --- 1. Connection ---
    game = await games_collection.find_one({"_id": game_id})
    if not game:
        await websocket.close(code=1008); return
    
    player_ids = [p['player_id'] for p in game['players']]
    if player_id not in player_ids:
        await websocket.close(code=1008); return

    await manager.connect(websocket, game_id, player_id)
    print(f"Player {player_id} connected to game {game_id}.")
    
    # Send the current state to the connecting player
    sanitized_state = sanitize_game_state_for_player(game['game_type'], game['game_state'], player_id)
    
    # Mark AI players in the player list
    players_with_ai_status = []
    for p in game['players']:
        player_dict = p.copy()
        player_dict['isAI'] = is_ai_player(game_id, p['player_id'])
        players_with_ai_status.append(player_dict)
    
    await websocket.send_json({
        "type": "connection_success",
        "game_state": sanitized_state,
        "players": players_with_ai_status,
        "game_type": game['game_type']
    })
    await manager.broadcast_to_game(game_id, {
        "type": "player_connected",
        "player_id": player_id
    })

    try:
        # --- 2. Message Loop ---
        while True:
            data = await websocket.receive_json()
            action_type = data.get('type')
            
            # --- Get fresh game doc for every action ---
            current_game = await games_collection.find_one({"_id": game_id})
            logic_module = GAME_LOGIC_MODULES.get(current_game['game_type'])
            if not logic_module:
                 await manager.send_to_player(game_id, player_id, {"type": "error", "message": "Unknown game type."})
                 continue
            
            if action_type == 'start_game':
                if current_game['host_id'] != player_id:
                    await manager.send_to_player(game_id, player_id, {"type": "error", "message": "Only the host can start."})
                    continue
                
                player_ids = [p['player_id'] for p in current_game['players']]
                current_count = len(player_ids)
                ai_needed = get_ai_players_needed(current_game['game_type'], current_count)
                
                # Auto-fill AI players to fill all missing slots
                if ai_needed > 0:
                    ai_players = []
                    for _ in range(ai_needed):
                        ai_player_id = generate_player_id()
                        ai_players.append({"player_id": ai_player_id})
                        player_ids.append(ai_player_id)
                    
                    # Add AI players to the game document
                    await games_collection.update_one(
                        {"_id": game_id},
                        {"$push": {"players": {"$each": ai_players}}}
                    )
                    
                    # Notify all players that AI players joined
                    for ai_player in ai_players:
                        await manager.broadcast_to_game(game_id, {
                            "type": "player_joined",
                            "player_id": ai_player["player_id"]
                        })
                    
                    # Refresh game document to get updated player list
                    current_game = await games_collection.find_one({"_id": game_id})
                    print(f"Auto-filled {ai_needed} AI player(s) to complete the game (now {len(player_ids)} total players)")
                
                try:
                    game_mode = current_game.get('game_mode', 'classic')
                    print(f"Starting {current_game['game_type']} game {game_id} with {len(player_ids)} players (mode: {game_mode})...")
                    if current_game['game_type'] == 'dominoes':
                        initial_state = logic_module.create_new_game(player_ids, game_mode)
                    else:  # blackjack
                        blackjack_mode = game_mode if game_mode in ['best_of_5', 'best_of_10'] else 'best_of_5'
                        initial_state = logic_module.create_new_game(player_ids, blackjack_mode)
                    
                    await games_collection.update_one(
                        {"_id": game_id},
                        {"$set": {"game_state": initial_state, "status": "in_progress"}}
                    )
                    
                    # Broadcast new state to all players with updated player list
                    current_game = await games_collection.find_one({"_id": game_id})
                    players_with_ai_status = []
                    for p in current_game['players']:
                        player_dict = p.copy()
                        player_dict['isAI'] = is_ai_player(game_id, p['player_id'])
                        players_with_ai_status.append(player_dict)
                    
                    for pid in player_ids:
                        sanitized = sanitize_game_state_for_player(current_game['game_type'], initial_state, pid)
                        await manager.send_to_player(game_id, pid, {
                            "type": "game_started",
                            "game_state": sanitized,
                            "players": players_with_ai_status
                        })
                    
                    # Process AI moves if the first player is an AI
                    await process_ai_moves(game_id, current_game['game_type'], initial_state)
                except ValueError as e:
                    error_msg = str(e)
                    await manager.send_to_player(game_id, player_id, {"type": "error", "message": error_msg})
                    print(f"Error starting game: {error_msg}")
                except Exception as e:
                    error_msg = f"Failed to start game: {str(e)}"
                    await manager.send_to_player(game_id, player_id, {"type": "error", "message": error_msg})
                    print(f"Unexpected error starting game: {e}")
            
            elif action_type == 'make_move':
                try:
                    new_state = logic_module.play_move(
                        current_game['game_state'], 
                        player_id, 
                        data['move_data']
                    )
                    
                    await games_collection.update_one(
                        {"_id": game_id},
                        {"$set": {"game_state": new_state}}
                    )

                    # Broadcast new state to all with updated player list
                    current_game = await games_collection.find_one({"_id": game_id})
                    players_with_ai_status = []
                    for p in current_game['players']:
                        player_dict = p.copy()
                        player_dict['isAI'] = is_ai_player(game_id, p['player_id'])
                        players_with_ai_status.append(player_dict)
                    
                    for pid in new_state['players']:
                        sanitized = sanitize_game_state_for_player(current_game['game_type'], new_state, pid)
                        await manager.send_to_player(game_id, pid, {
                            "type": "state_update",
                            "game_state": sanitized,
                            "players": players_with_ai_status
                        })
                    
                    # If round finished, auto-mark AI players as ready immediately
                    if current_game['game_type'] == 'blackjack' and new_state.get('status') == 'round_finished':
                        if 'ready_for_next_round' not in new_state:
                            new_state['ready_for_next_round'] = {}
                        
                        all_players = new_state['players']
                        ai_ready_count = 0
                        for pid in all_players:
                            if is_ai_player(game_id, pid):
                                new_state['ready_for_next_round'][pid] = True
                                ai_ready_count += 1
                        
                        if ai_ready_count > 0:
                            new_state['log'].append(f"✓ {ai_ready_count} AI player(s) automatically ready for next round")
                            
                            await games_collection.update_one(
                                {"_id": game_id},
                                {"$set": {"game_state": new_state}}
                            )
                            
                            # Broadcast updated state with AI ready
                            current_game = await games_collection.find_one({"_id": game_id})
                            players_with_ai_status = []
                            for p in current_game['players']:
                                player_dict = p.copy()
                                player_dict['isAI'] = is_ai_player(game_id, p['player_id'])
                                players_with_ai_status.append(player_dict)
                            
                            for pid in all_players:
                                sanitized = sanitize_game_state_for_player(current_game['game_type'], new_state, pid)
                                await manager.send_to_player(game_id, pid, {
                                    "type": "state_update",
                                    "game_state": sanitized,
                                    "players": players_with_ai_status
                                })
                            
                            # Check if all players are ready (including AI)
                            ready_count = len(new_state['ready_for_next_round'])
                            total_players = len(all_players)
                            
                            if ready_count >= total_players:
                                # All players ready, start next round immediately
                                await asyncio.sleep(0.5)  # Brief pause
                                
                                # Create new round
                                player_ids = new_state['players']
                                game_mode = new_state.get('game_mode', 'best_of_5')
                                next_round_number = new_state.get('round_number', 1) + 1
                                next_round_state = logic_module.create_new_game(player_ids, game_mode)
                                
                                # Preserve game-level state
                                next_round_state['hand_wins'] = new_state.get('hand_wins', {})
                                next_round_state['round_number'] = next_round_number
                                next_round_state['scores'] = new_state.get('scores', {})
                                next_round_state['game_mode'] = game_mode
                                next_round_state['wins_needed'] = new_state.get('wins_needed', 3)
                                next_round_state['log'] = [f"🔄 Starting Round #{next_round_number}..."] + next_round_state['log']
                                
                                await games_collection.update_one(
                                    {"_id": game_id},
                                    {"$set": {"game_state": next_round_state}}
                                )
                                
                                # Broadcast new round state
                                current_game = await games_collection.find_one({"_id": game_id})
                                players_with_ai_status = []
                                for p in current_game['players']:
                                    player_dict = p.copy()
                                    player_dict['isAI'] = is_ai_player(game_id, p['player_id'])
                                    players_with_ai_status.append(player_dict)
                                
                                for pid in player_ids:
                                    sanitized = sanitize_game_state_for_player(current_game['game_type'], next_round_state, pid)
                                    await manager.send_to_player(game_id, pid, {
                                        "type": "state_update",
                                        "game_state": sanitized,
                                        "players": players_with_ai_status
                                    })
                                
                                # Process AI moves if needed
                                await process_ai_moves(game_id, current_game['game_type'], next_round_state)
                                continue  # Skip processing AI moves for the finished round
                    
                    # Process AI moves until it's a human player's turn or game ends
                    await process_ai_moves(game_id, current_game['game_type'], new_state)
                except ValueError as e:
                    await manager.send_to_player(game_id, player_id, {"type": "error", "message": str(e)})
                except Exception as e:
                    error_msg = f"Failed to process move: {str(e)}"
                    await manager.send_to_player(game_id, player_id, {"type": "error", "message": error_msg})
                    print(f"Unexpected error processing move: {e}")
            
            elif action_type == 'ready_for_next_round':
                # Player is ready for next round (blackjack only)
                if current_game['game_type'] != 'blackjack':
                    await manager.send_to_player(game_id, player_id, {"type": "error", "message": "This action is only for blackjack."})
                    continue
                
                game_state = current_game['game_state']
                if game_state.get('status') != 'round_finished':
                    await manager.send_to_player(game_id, player_id, {"type": "error", "message": "No round is finished."})
                    continue
                
                # Mark player as ready
                if 'ready_for_next_round' not in game_state:
                    game_state['ready_for_next_round'] = {}
                
                game_state['ready_for_next_round'][player_id] = True
                
                # Check if all players are ready
                all_players = game_state['players']
                
                # Auto-mark ALL AI players as ready immediately (not just after human clicks)
                ai_ready_count = 0
                for pid in all_players:
                    if is_ai_player(game_id, pid) and pid not in game_state['ready_for_next_round']:
                        game_state['ready_for_next_round'][pid] = True
                        ai_ready_count += 1
                
                if ai_ready_count > 0:
                    game_state['log'].append(f"✓ {ai_ready_count} AI player(s) automatically ready for next round")
                
                ready_count = len(game_state['ready_for_next_round'])
                total_players = len(all_players)
                
                game_state['log'].append(f"✓ Player is ready for next round ({ready_count}/{total_players})")
                
                await games_collection.update_one(
                    {"_id": game_id},
                    {"$set": {"game_state": game_state}}
                )
                
                # Broadcast updated state
                current_game = await games_collection.find_one({"_id": game_id})
                players_with_ai_status = []
                for p in current_game['players']:
                    player_dict = p.copy()
                    player_dict['isAI'] = is_ai_player(game_id, p['player_id'])
                    players_with_ai_status.append(player_dict)
                
                for pid in all_players:
                    sanitized = sanitize_game_state_for_player(current_game['game_type'], game_state, pid)
                    await manager.send_to_player(game_id, pid, {
                        "type": "state_update",
                        "game_state": sanitized,
                        "players": players_with_ai_status
                    })
                
                # Check if all players are ready now (including AI)
                ready_count = len(game_state['ready_for_next_round'])
                
                if ready_count >= total_players:
                    # Update database with AI ready status
                    await games_collection.update_one(
                        {"_id": game_id},
                        {"$set": {"game_state": game_state}}
                    )
                    
                    # Broadcast updated state
                    current_game = await games_collection.find_one({"_id": game_id})
                    players_with_ai_status = []
                    for p in current_game['players']:
                        player_dict = p.copy()
                        player_dict['isAI'] = is_ai_player(game_id, p['player_id'])
                        players_with_ai_status.append(player_dict)
                    
                    for pid in all_players:
                        sanitized = sanitize_game_state_for_player(current_game['game_type'], game_state, pid)
                        await manager.send_to_player(game_id, pid, {
                            "type": "state_update",
                            "game_state": sanitized,
                            "players": players_with_ai_status
                        })
                    
                    await asyncio.sleep(0.5)  # Brief pause
                    
                    # Create new round
                    player_ids = game_state['players']
                    game_mode = game_state.get('game_mode', 'best_of_5')
                    next_round_number = game_state.get('round_number', 1) + 1
                    next_round_state = logic_module.create_new_game(player_ids, game_mode)
                    
                    # Preserve game-level state
                    next_round_state['hand_wins'] = game_state.get('hand_wins', {})
                    next_round_state['round_number'] = next_round_number
                    next_round_state['scores'] = game_state.get('scores', {})
                    next_round_state['game_mode'] = game_mode
                    next_round_state['wins_needed'] = game_state.get('wins_needed', 3)
                    next_round_state['log'] = [f"🔄 Starting Round #{next_round_number}..."] + next_round_state['log']
                    
                    await games_collection.update_one(
                        {"_id": game_id},
                        {"$set": {"game_state": next_round_state}}
                    )
                    
                    # Broadcast new round state
                    current_game = await games_collection.find_one({"_id": game_id})
                    players_with_ai_status = []
                    for p in current_game['players']:
                        player_dict = p.copy()
                        player_dict['isAI'] = is_ai_player(game_id, p['player_id'])
                        players_with_ai_status.append(player_dict)
                    
                    for pid in player_ids:
                        sanitized = sanitize_game_state_for_player(current_game['game_type'], next_round_state, pid)
                        await manager.send_to_player(game_id, pid, {
                            "type": "state_update",
                            "game_state": sanitized,
                            "players": players_with_ai_status
                        })
                    
                    # Process AI moves if needed
                    await process_ai_moves(game_id, current_game['game_type'], next_round_state)
            
            elif action_type == 'ready_for_next_hand':
                # Player is ready for next hand (dominoes only)
                if current_game['game_type'] != 'dominoes':
                    await manager.send_to_player(game_id, player_id, {"type": "error", "message": "This action is only for dominoes."})
                    continue
                
                game_state = current_game['game_state']
                if game_state.get('status') != 'hand_finished':
                    await manager.send_to_player(game_id, player_id, {"type": "error", "message": "No hand is finished."})
                    continue
                
                # Mark player as ready
                if 'ready_for_next_hand' not in game_state:
                    game_state['ready_for_next_hand'] = {}
                
                game_state['ready_for_next_hand'][player_id] = True
                
                # Check if all players are ready
                all_players = game_state['players']
                ready_count = len(game_state['ready_for_next_hand'])
                total_players = len(all_players)
                
                game_state['log'].append(f"✓ {player_id} is ready for next hand ({ready_count}/{total_players})")
                
                await games_collection.update_one(
                    {"_id": game_id},
                    {"$set": {"game_state": game_state}}
                )
                
                # Broadcast updated state
                current_game = await games_collection.find_one({"_id": game_id})
                players_with_ai_status = []
                for p in current_game['players']:
                    player_dict = p.copy()
                    player_dict['isAI'] = is_ai_player(game_id, p['player_id'])
                    players_with_ai_status.append(player_dict)
                
                for pid in all_players:
                    sanitized = sanitize_game_state_for_player(current_game['game_type'], game_state, pid)
                    await manager.send_to_player(game_id, pid, {
                        "type": "state_update",
                        "game_state": sanitized,
                        "players": players_with_ai_status
                    })
                
                # Auto-mark AI players as ready
                for pid in all_players:
                    if is_ai_player(game_id, pid) and pid not in game_state['ready_for_next_hand']:
                        game_state['ready_for_next_hand'][pid] = True
                        game_state['log'].append(f"✓ {pid} (AI) is ready for next hand")
                
                # Update ready count after AI auto-ready
                ready_count = len(game_state['ready_for_next_hand'])
                
                if ready_count >= total_players:
                    # Update database with AI ready status
                    await games_collection.update_one(
                        {"_id": game_id},
                        {"$set": {"game_state": game_state}}
                    )
                    
                    # Broadcast updated state
                    current_game = await games_collection.find_one({"_id": game_id})
                    players_with_ai_status = []
                    for p in current_game['players']:
                        player_dict = p.copy()
                        player_dict['isAI'] = is_ai_player(game_id, p['player_id'])
                        players_with_ai_status.append(player_dict)
                    
                    for pid in all_players:
                        sanitized = sanitize_game_state_for_player(current_game['game_type'], game_state, pid)
                        await manager.send_to_player(game_id, pid, {
                            "type": "state_update",
                            "game_state": sanitized,
                            "players": players_with_ai_status
                        })
                    
                    await asyncio.sleep(0.5)  # Brief pause
                    
                    # Create new hand
                    player_ids = game_state['players']
                    game_mode = game_state.get('game_mode', 'classic')
                    current_hand_num = game_state.get('hand_number', 1)
                    next_hand_number = current_hand_num + 1 if game_mode == 'classic' else game_state.get('hand_number', 2)
                    
                    # Check if we need to set a specific starter (from deadlock tie)
                    next_hand_starter = game_state.get('next_hand_starter')
                    
                    next_hand_state = logic_module.create_new_game(player_ids, game_mode)
                    
                    # If next_hand_starter is set (from deadlock tie), override the starting player
                    if next_hand_starter and game_mode == "boricua" and next_hand_state.get('teams'):
                        teams = next_hand_state['teams']
                        if next_hand_starter in teams:
                            # Set the first player of the specified team as starter
                            starting_team_players = teams[next_hand_starter]
                            if starting_team_players:
                                # Find the starting player from that team
                                start_player_id = starting_team_players[0]
                                # Find highest double in that team's hands
                                start_tile = None
                                for double in range(6, -1, -1):
                                    tile = (double, double)
                                    for player_id in starting_team_players:
                                        if tile in next_hand_state['hands'][player_id]:
                                            start_player_id = player_id
                                            start_tile = tile
                                            break
                                    if start_tile:
                                        break
                                
                                # If no double, find highest pip tile in that team
                                if not start_tile:
                                    max_pips = -1
                                    for player_id in starting_team_players:
                                        for tile in next_hand_state['hands'][player_id]:
                                            if sum(tile) > max_pips:
                                                max_pips = sum(tile)
                                                start_player_id = player_id
                                
                                # Update the game state to start with this player
                                next_hand_state['current_turn_index'] = player_ids.index(start_player_id)
                                
                                # If a starting tile was found, play it
                                if start_tile:
                                    next_hand_state['board'].append(start_tile)
                                    next_hand_state['hands'][start_player_id].remove(start_tile)
                                    next_hand_state['current_turn_index'] = (next_hand_state['current_turn_index'] + 1) % len(player_ids)
                                    next_hand_state['last_tile_played'] = start_tile
                                    next_hand_state['log'].append(f"{start_player_id} started with {start_tile} (team who started previous hand).")
                    
                    # Preserve game-level state
                    next_hand_state['hand_wins'] = game_state.get('hand_wins', {})
                    next_hand_state['hand_number'] = next_hand_number
                    next_hand_state['scores'] = game_state.get('scores', {})
                    next_hand_state['teams'] = game_state.get('teams')
                    next_hand_state['team_scores'] = game_state.get('team_scores')
                    next_hand_state['log'] = [f"🔄 Starting Hand #{next_hand_number}..."] + next_hand_state['log']
                    
                    await games_collection.update_one(
                        {"_id": game_id},
                        {"$set": {"game_state": next_hand_state}}
                    )
                    
                    # Broadcast new hand state
                    current_game = await games_collection.find_one({"_id": game_id})
                    players_with_ai_status = []
                    for p in current_game['players']:
                        player_dict = p.copy()
                        player_dict['isAI'] = is_ai_player(game_id, p['player_id'])
                        players_with_ai_status.append(player_dict)
                    
                    for pid in player_ids:
                        sanitized = sanitize_game_state_for_player(current_game['game_type'], next_hand_state, pid)
                        await manager.send_to_player(game_id, pid, {
                            "type": "state_update",
                            "game_state": sanitized,
                            "players": players_with_ai_status
                        })
                    
                    # Process AI moves if needed
                    await process_ai_moves(game_id, current_game['game_type'], next_hand_state)

    except WebSocketDisconnect:
        print(f"Player {player_id} disconnected from game {game_id}.")
        manager.disconnect(game_id, player_id)
        await manager.broadcast_to_game(game_id, {
            "type": "player_disconnected",
            "player_id": player_id
        })

# --- Serve Frontend ---
app.mount("/static", StaticFiles(directory="../frontend"), name="static")

@app.get("/")
async def read_index():
    return FileResponse('../frontend/index.html')

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)