from flask import Flask, render_template, request, jsonify, send_from_directory
import uuid
from datetime import datetime
from game import Game

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 86400

# Game state
games = {}  # game_id -> game_state
players = {}  # player_id -> player_info

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/google146aae795db1900e.html')
def google_verification():
    return send_from_directory('.', 'google146aae795db1900e.html')

@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('.', 'sitemap.xml')

@app.route('/robots.txt')
def robots():
    return send_from_directory('.', 'robots.txt')


@app.route('/room/<game_id>')
def room(game_id):
    return render_template('index.html')

@app.route('/api/create_game', methods=['POST'])
def create_game():
    game_id = str(uuid.uuid4())[:4]
    games[game_id] = Game(game_id)
    return jsonify({'game_id': game_id})

@app.route('/api/join_game', methods=['POST'])
def join_game():
    data = request.json
    game_id = data['game_id']
    player_name = data['player_name']

    if game_id not in games:
        return jsonify({'success': False, 'message': 'Game not found'}), 404

    game = games[game_id]
    success, player_id, error_msg = game.join_player(player_name)

    if not success:
        return jsonify({'success': False, 'message': error_msg}), 400

    players[player_id] = {'game_id': game_id, 'name': player_name}
    return jsonify({
        'success': True,
        'player_id': player_id,
        'game_state': game.get_state()
    })

@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    data = request.json
    game_id = data['game_id']
    player_id = data['player_id']

    if game_id not in games:
        return jsonify({'success': False}), 404

    game = games[game_id]
    if player_id in game.players:
        game.players[player_id]['connected'] = True
        game.last_heartbeat[player_id] = datetime.now().timestamp()

    return jsonify({'success': True})

@app.route('/api/start_game', methods=['POST'])
def start_game():
    data = request.json
    game_id = data['game_id']

    game = games[game_id]
    if len(game.players) < 3:
        return jsonify({'success': False, 'message': 'Need 3 players to start'}), 400

    game.status = 'bidding'
    game.deal_cards()
    game.current_player = list(game.players.keys())[0]

    return jsonify({'success': True, 'game_state': game.get_state()})

@app.route('/api/disconnect', methods=['POST'])
def disconnect():
    game_id = request.form.get('game_id') or (request.json.get('game_id') if request.json else None)
    player_id = request.form.get('player_id') or (request.json.get('player_id') if request.json else None)

    if not game_id or not player_id:
        return jsonify({'success': False}), 400

    if game_id not in games:
        return jsonify({'success': False}), 404

    game = games[game_id]
    if player_id in game.players:
        game.players[player_id]['connected'] = False

    # Check if all players are disconnected, and delete the game if so
    all_disconnected = all(not player['connected'] for player in game.players.values())
    if all_disconnected:
        del games[game_id]

    return jsonify({'success': True})

@app.route('/api/game_state/<game_id>')
def get_game_state(game_id):
    if game_id not in games:
        return jsonify({'error': 'Game not found'}), 404

    return jsonify(games[game_id].get_state())

@app.route('/api/player_hand/<game_id>/<player_id>')
def get_player_hand(game_id, player_id):
    if game_id not in games:
        return jsonify({'error': 'Game not found'}), 404

    game = games[game_id]
    if player_id not in game.players:
        return jsonify({'error': 'Player not found'}), 404

    hand = game.players[player_id]['hand']
    # Sort cards by rank value
    sorted_hand = sorted(hand, key=lambda card: card.get_rank_value())
    return jsonify({'hand': [card.to_dict() for card in sorted_hand]})

@app.route('/api/restart_game', methods=['POST'])
def restart_game():
    data = request.json
    game_id = data['game_id']

    game = games[game_id]
    # Keep players and their scores, but reset game state
    game.status = 'bidding'

    if game.winner and game.winner in game.players:
        game.current_player = game.winner
    else:
        game.current_player = list(game.players.keys())[0]

    game.landlord = None
    game.landlord_caller = None
    game.landlord_cards = []
    game.bid_pool = 1
    game.take_count = 0
    game.passed_players = set()
    game.round_winner = None
    game.round_starter = None
    game.last_played = None
    game.last_combo_type = None
    game.last_combo_value = None
    game.last_combo_chain = None
    game.winner = None

    # Deal new cards
    game.deal_cards()

    return jsonify(game.get_state())

@app.route('/api/bid_landlord', methods=['POST'])
def bid_landlord():
    data = request.json
    game_id = data['game_id']
    player_id = data['player_id']
    action = data['action']  # 'call', 'take', or 'pass'

    game = games[game_id]
    success, error_msg = game.bid_landlord(player_id, action)

    if not success:
        return jsonify({'success': False, 'message': error_msg}), 400

    return jsonify(game.get_state())

@app.route('/api/play_cards', methods=['POST'])
def play_cards():
    data = request.json
    game_id = data['game_id']
    player_id = data['player_id']
    cards_data = data.get('cards', [])  # Empty means pass

    game = games[game_id]
    success, error_msg = game.play_cards(player_id, cards_data)

    if not success:
        return jsonify({'success': False, 'message': error_msg}), 400

    return jsonify(game.get_state())

if __name__ == '__main__':
    app.run(debug=True)
