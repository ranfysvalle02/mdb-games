# backend/domino_logic.py
import random
from collections import deque

def create_boneyard(max_pips=6):
    boneyard = [(i, j) for i in range(max_pips + 1) for j in range(i, max_pips + 1)]
    random.shuffle(boneyard)
    return boneyard

def create_new_game(player_ids: list[str], game_mode: str = "classic"):
    """
    Sets up a new game, deals hands, and finds the starting player.
    game_mode: "classic" (best of 5, no prizes) or "boricua" (first to 500, with prizes)
    """
    if not 2 <= len(player_ids) <= 4:
        raise ValueError("Dominoes must have 2 to 4 players.")
    
    if game_mode == "boricua" and len(player_ids) != 4:
        raise ValueError("Boricua style requires exactly 4 players (2v2).")
        
    boneyard = create_boneyard()
    hands = {player_id: [] for player_id in player_ids}
    
    # Deal 7 tiles each
    for _ in range(7):
        for player_id in player_ids:
            if not boneyard:
                break
            hands[player_id].append(boneyard.pop())

    # Check if we need to use a specific starter from previous hand (deadlock tie)
    start_player_id = None
    start_tile = None
    
    # If next_hand_starter is set (from deadlock tie), use that team's first player
    if game_mode == "boricua" and teams:
        # This will be set when creating next hand after deadlock tie
        # For now, find normally
        pass
    
    # Find starting player (highest double)
    if not start_player_id:
        for double in range(6, -1, -1):
            tile = (double, double)
            for player_id, hand in hands.items():
                if tile in hand:
                    start_player_id = player_id
                    start_tile = tile
                    break
            if start_player_id:
                break

    # If no double, find highest pip tile
    if not start_player_id:
        max_pips = -1
        for player_id, hand in hands.items():
            for tile in hand:
                if sum(tile) > max_pips:
                    max_pips = sum(tile)
                    start_player_id = player_id
        start_tile = None 

    # Initialize scoring
    scores = {player_id: 0 for player_id in player_ids}
    hand_wins = {player_id: 0 for player_id in player_ids}
    hand_number = 1
    
    # For Boricua style, organize teams (first 2 vs last 2)
    teams = None
    if game_mode == "boricua":
        teams = {
            "team1": player_ids[:2],
            "team2": player_ids[2:]
        }
        team_scores = {"team1": 0, "team2": 0}

    game_state = {
        "board": [], # A list for easier JSON/Mongo storage
        "hands": hands,
        "boneyard": boneyard,
        "players": player_ids,
        "current_turn_index": player_ids.index(start_player_id),
        "status": "in_progress",
        "last_move_was_capicu": False,
        "last_tile_played": None,
        "passes_in_a_row": 0,
        "winner": None,
        "game_mode": game_mode,
        "scores": scores,
        "hand_wins": hand_wins,
        "hand_number": hand_number,
        "teams": teams,
        "team_scores": team_scores if game_mode == "boricua" else None,
        "starting_player_id": start_player_id,  # Track who started this hand
        "log": [f"Game started ({game_mode.upper()} mode). {start_player_id} goes first."]
    }

    # If a starting double was found, play it automatically
    if start_tile:
        game_state['board'].append(start_tile)
        game_state['hands'][start_player_id].remove(start_tile)
        game_state['current_turn_index'] = (game_state['current_turn_index'] + 1) % len(player_ids)
        game_state['last_tile_played'] = start_tile
        game_state['log'].append(f"{start_player_id} started with {start_tile}.")
        
    return game_state

def get_open_ends(board: list):
    if not board:
        return None, None
    return board[0][0], board[-1][1]

def play_move(game_state: dict, player_id: str, move_data: dict):
    """
    Takes the current game state and a move, validates it,
    and returns the new game state.
    """
    
    turn_index = game_state['current_turn_index']
    turn_player_id = game_state['players'][turn_index]
    
    if player_id != turn_player_id:
        raise ValueError("It's not your turn.")
    
    action = move_data.get('action')
    hand = game_state['hands'][player_id]

    if action == "pass":
        if game_state['boneyard']:
            raise ValueError("You must draw from the boneyard, not pass.")
        
        game_state['passes_in_a_row'] += 1
        game_state['log'].append(f"{player_id} passed.")

        if game_state['passes_in_a_row'] >= len(game_state['players']):
            # Game is blocked - check for deadlock in Boricua style
            game_mode = game_state.get('game_mode', 'classic')
            
            if game_mode == "boricua":
                # Check for deadlock: all 7 tiles with 5 are out, both ends are 5/5
                board = game_state['board']
                left_end, right_end = get_open_ends(board)
                
                # Count how many tiles with 5 are on the board
                tiles_with_5_on_board = sum(1 for tile in board if 5 in tile)
                
                # Check if deadlock condition: both ends are 5, and all 7 tiles with 5 are out
                is_deadlock = (left_end == 5 and right_end == 5 and tiles_with_5_on_board == 7)
                
                if is_deadlock:
                    # Deadlock! Calculate points for each team
                    teams = game_state.get('teams')
                    team_scores = game_state.get('team_scores')
                    
                    if teams and team_scores:
                        # Calculate points in hand for each team
                        team1_points = sum(sum(tile) for player_id in teams['team1'] for tile in game_state['hands'][player_id])
                        team2_points = sum(sum(tile) for player_id in teams['team2'] for tile in game_state['hands'][player_id])
                        
                        if team1_points < team2_points:
                            # Team 1 wins (least points)
                            points_awarded = team1_points + team2_points
                            team_scores['team1'] += points_awarded
                            game_state['log'].append(f"🔒 DEADLOCK! All 5s are out, both ends are 5/5.")
                            game_state['log'].append(f"🏆 TEAM1 WINS (least points: {team1_points} vs {team2_points}) - {points_awarded} POINTS!")
                            game_state['log'].append(f"📊 SCORES: {teams['team1']} = {team_scores['team1']} | {teams['team2']} = {team_scores['team2']}")
                            
                            # Check if team reached 500
                            if team_scores['team1'] >= 500:
                                game_state['status'] = "finished"
                                game_state['winner'] = "team1"
                                game_state['log'].append(f"🎊🎊🎊 TEAM1 WINS THE GAME! 🎊🎊🎊")
                            else:
                                game_state['status'] = "hand_finished"
                                game_state['winner'] = "team1"
                                game_state['hand_number'] += 1
                                game_state['ready_for_next_hand'] = {}
                                game_state['log'].append(f"🏆 Hand {game_state['hand_number'] - 1} complete! All players must click 'Next Hand' to continue.")
                        elif team2_points < team1_points:
                            # Team 2 wins (least points)
                            points_awarded = team1_points + team2_points
                            team_scores['team2'] += points_awarded
                            game_state['log'].append(f"🔒 DEADLOCK! All 5s are out, both ends are 5/5.")
                            game_state['log'].append(f"🏆 TEAM2 WINS (least points: {team2_points} vs {team1_points}) - {points_awarded} POINTS!")
                            game_state['log'].append(f"📊 SCORES: {teams['team1']} = {team_scores['team1']} | {teams['team2']} = {team_scores['team2']}")
                            
                            # Check if team reached 500
                            if team_scores['team2'] >= 500:
                                game_state['status'] = "finished"
                                game_state['winner'] = "team2"
                                game_state['log'].append(f"🎊🎊🎊 TEAM2 WINS THE GAME! 🎊🎊🎊")
                            else:
                                game_state['status'] = "hand_finished"
                                game_state['winner'] = "team2"
                                game_state['hand_number'] += 1
                                game_state['ready_for_next_hand'] = {}
                                game_state['log'].append(f"🏆 Hand {game_state['hand_number'] - 1} complete! All players must click 'Next Hand' to continue.")
                        else:
                            # Tie - nobody wins, team who started starts next round
                            game_state['log'].append(f"🔒 DEADLOCK! All 5s are out, both ends are 5/5.")
                            game_state['log'].append(f"🤝 TIE! Both teams have {team1_points} points. Nobody wins.")
                            
                            # Find which team started (use starting_player_id from game state)
                            starting_player_id = game_state.get('starting_player_id')
                            if not starting_player_id:
                                # Fallback: use first player if not tracked
                                starting_player_id = game_state['players'][0]
                            
                            # Determine which team started
                            starting_team = None
                            if starting_player_id in teams['team1']:
                                starting_team = "team1"
                            else:
                                starting_team = "team2"
                            
                            game_state['log'].append(f"🔄 {starting_team.upper()} started this hand, so they start the next round.")
                            
                            game_state['status'] = "hand_finished"
                            game_state['winner'] = None
                            game_state['hand_number'] += 1
                            game_state['ready_for_next_hand'] = {}
                            game_state['next_hand_starter'] = starting_team  # Track for next hand
                            game_state['log'].append(f"🏆 Hand {game_state['hand_number'] - 1} complete! All players must click 'Next Hand' to continue.")
                else:
                    # Regular block (not deadlock) - handle normally
                    game_state['status'] = "finished"
                    game_state['winner'] = "blocked"
                    game_state['log'].append("Game is blocked!")
            else:
                # Classic mode - handle normally
                game_state['status'] = "finished"
                game_state['winner'] = "blocked"
                game_state['log'].append("Game is blocked!")
        
    elif action == "draw":
        if not game_state['boneyard']:
            raise ValueError("Boneyard is empty, you must pass.")
            
        new_tile = game_state['boneyard'].pop()
        hand.append(new_tile)
        game_state['log'].append(f"{player_id} drew a tile.")
        
    elif action == "play":
        tile = tuple(move_data.get('tile')) # e.g., [6, 5] -> (6, 5)
        side = move_data.get('side') # 'left' or 'right'
        
        # Find the actual tile in hand (handle both tuples and lists)
        actual_tile = None
        for hand_tile in hand:
            # Normalize both for comparison
            norm_hand_tile = tuple(hand_tile) if isinstance(hand_tile, list) else hand_tile
            if tile == norm_hand_tile or tile == tuple(reversed(norm_hand_tile)):
                actual_tile = hand_tile
                # Use normalized version for playing
                tile = norm_hand_tile if tile == norm_hand_tile else tuple(reversed(norm_hand_tile))
                break
        
        if actual_tile is None:
            raise ValueError("You don't have that tile.")
        
        board = game_state['board']
        left_end, right_end = get_open_ends(board)
        
        game_state['passes_in_a_row'] = 0
        hand.remove(actual_tile)  # Remove the actual tile from hand
        game_state['last_tile_played'] = tile

        if not board:
            board.append(tile)
        elif side == 'left':
            if tile[1] == left_end: board.insert(0, tile)
            elif tile[0] == left_end: board.insert(0, (tile[1], tile[0]))
            else: raise ValueError("Tile doesn't match the left end.")
        elif side == 'right':
            if tile[0] == right_end: board.append(tile)
            elif tile[1] == right_end: board.append((tile[1], tile[0]))
            else: raise ValueError("Tile doesn't match the right end.")

        game_state['log'].append(f"{player_id} played {tile}.")

        if not hand:
            # Hand finished - calculate points
            game_mode = game_state.get('game_mode', 'classic')
            winner_id = player_id
            points_awarded = 0
            won_with_chucha = (tile == (0, 0))
            
            # Bonus checks
            new_left, new_right = get_open_ends(board)
            is_capicu = (tile[0] == new_right or tile[1] == new_right) and \
                       (tile[0] == new_left or tile[1] == new_left)
            if is_capicu:
                game_state['last_move_was_capicu'] = True
                game_state['log'].append("🎉 ¡CAPICÚ!")
            
            if game_mode == "classic":
                # Classic: Best of 5, no prizes
                game_state['hand_wins'][winner_id] += 1
                game_state['log'].append(f"🏆 {winner_id} WINS HAND #{game_state['hand_number']}!")
                
                # Check if someone won best of 5
                if game_state['hand_wins'][winner_id] >= 3:
                    game_state['status'] = "finished"
                    game_state['winner'] = winner_id
                    game_state['log'].append(f"🎊🎊🎊 {winner_id} WINS THE GAME (Best of 5)! 🎊🎊🎊")
                else:
                    # Start new hand - wait for all players to be ready
                    game_state['status'] = "hand_finished"
                    game_state['winner'] = winner_id
                    game_state['ready_for_next_hand'] = {}  # Track who's ready: {player_id: True}
                    game_state['log'].append(f"🏆 Hand {game_state['hand_number']} complete! All players must click 'Next Hand' to continue.")
                    
            elif game_mode == "boricua":
                # Boricua: First to 500, with prizes
                hand_num = game_state['hand_number']
                
                # Determine points based on hand number
                if hand_num == 1:
                    points_awarded = 100
                elif hand_num == 2:
                    points_awarded = 75
                elif hand_num == 3:
                    points_awarded = 50
                elif hand_num == 4:
                    points_awarded = 25
                else:
                    points_awarded = 25  # Default for additional hands
                
                # Bonus for winning with 0/0 (LA CHUCHA)
                if won_with_chucha:
                    points_awarded += 100
                    game_state['log'].append("💥 ¡LA CHUCHA! +100 BONUS POINTS!")
                
                # Award points to team
                teams = game_state.get('teams')
                team_scores = game_state.get('team_scores')
                if teams and team_scores:
                    # Find which team the winner is on
                    winning_team = None
                    for team_name, team_players in teams.items():
                        if winner_id in team_players:
                            winning_team = team_name
                            break
                    
                    if winning_team:
                        team_scores[winning_team] += points_awarded
                        game_state['log'].append(f"🏆 {winning_team.upper()} WINS HAND #{hand_num} - {points_awarded} POINTS!")
                        game_state['log'].append(f"📊 SCORES: {teams['team1']} = {team_scores['team1']} | {teams['team2']} = {team_scores['team2']}")
                        
                        # Check if a team reached 500
                        if team_scores[winning_team] >= 500:
                            game_state['status'] = "finished"
                            game_state['winner'] = winning_team
                            game_state['log'].append(f"🎊🎊🎊 {winning_team.upper()} WINS THE GAME! 🎊🎊🎊")
                        else:
                            # Start new hand - wait for all players to be ready
                            game_state['status'] = "hand_finished"
                            game_state['winner'] = winning_team
                            game_state['hand_number'] += 1
                            game_state['ready_for_next_hand'] = {}  # Track who's ready: {player_id: True}
                            game_state['log'].append(f"🏆 Hand {hand_num} complete! All players must click 'Next Hand' to continue.")
            
            if won_with_chucha and game_mode != "boricua":
                game_state['log'].append("💥 ¡CHUCHAZO! (Won with 0-0)")

    else:
        raise ValueError("Invalid action.")

    # Advance Turn
    if game_state['status'] == 'in_progress':
        # Only advance turn if player didn't just draw
        if action != "draw":
             game_state['current_turn_index'] = (turn_index + 1) % len(game_state['players'])
    
    return game_state