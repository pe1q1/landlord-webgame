from flask import Flask, render_template, request, jsonify, send_from_directory
import random
import uuid
from datetime import datetime

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 86400

# Game state
games = {}  # game_id -> game_state
players = {}  # player_id -> player_info

class Card:
    ranks = ['3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A', '2', 'BJ', 'RJ']
    suits = ['♠', '♥', '♦', '♣']

    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit

    def get_rank_value(self):
        return Card.ranks.index(self.rank)

    def to_dict(self):
        return {'rank': self.rank, 'suit': self.suit}

    def __repr__(self):
        return f"{self.suit}{self.rank}"

class Game:
    def __init__(self, game_id):
        self.game_id = game_id
        self.players = {}
        self.deck = []
        self.played_cards = {}
        self.current_player = None
        self.landlord = None
        self.status = 'waiting'  # waiting, bidding, playing, finished
        self.round_winner = None
        self.last_played = None
        self.last_combo_type = None  # Type of last played combination
        self.last_combo_value = None  # Base value of last combination
        self.last_combo_chain = None  # Chain length for straights/airplanes
        self.bid_pool = 1  # Starting bid pool
        self.take_count = 0  # Number of times landlord has been taken
        self.landlord_caller = None  # Person who initially called for landlord
        self.landlord_cards = []  # 3 cards for landlord
        self.passed_players = set()  # Players who have passed in current bidding round
        self.winner = None  # Player ID of winner
        self.round_starter = None  # Player who starts the current round (first play)
        self.last_heartbeat = {}  # player_id -> timestamp of last activity

    def create_deck(self):
        self.deck = []
        for rank in Card.ranks[:-2]:
            for suit in Card.suits:
                self.deck.append(Card(rank, suit))
        # Add jokers
        self.deck.append(Card('BJ', ''))
        self.deck.append(Card('RJ', ''))
        random.shuffle(self.deck)

    def deal_cards(self):
        self.create_deck()
        cards_per_player = 17
        player_ids = list(self.players.keys())

        for i, player_id in enumerate(player_ids):
            self.players[player_id]['hand'] = []
            for j in range(cards_per_player):
                self.players[player_id]['hand'].append(self.deck[i * cards_per_player + j])

        # Remaining 3 cards for landlord (stored in game, not player)
        self.landlord_cards = self.deck[51:54]

    def format_combo_display(self, combo_type, chain_length):
        """Format combo type into readable display text"""
        if combo_type == 'single':
            return 'Single'
        elif combo_type == 'pair':
            return 'Pair'
        elif combo_type == 'triple':
            return 'Triple'
        elif combo_type == 'triple_single':
            return 'Triple + Single'
        elif combo_type == 'triple_pair':
            return 'Triple + Pair'
        elif combo_type == 'straight':
            return f'Straight ({chain_length})'
        elif combo_type == 'pair_straight':
            return f'Pair Straight ({chain_length})'
        elif combo_type == 'triple_straight':
            return f'Triple Straight ({chain_length})'
        elif combo_type == 'triple_straight_single':
            return f'Airplane ({chain_length})'
        elif combo_type == 'triple_straight_pair':
            return f'Airplane with Wings ({chain_length})'
        elif combo_type == 'four_two_single':
            return 'Four + Two'
        elif combo_type == 'four_two_pair':
            return 'Four + Two Pairs'
        elif combo_type == 'bomb':
            return 'Bomb'
        elif combo_type == 'rocket':
            return 'Rocket'
        return 'Unknown'

    def classify_hand(self, cards):
        """
        Classify a hand of cards into a valid combination type.
        Returns: (combo_type, base_value, chain_length) or (None, None, None) if invalid

        Combo types:
        - 'single': 1 card
        - 'pair': 2 cards same rank
        - 'triple': 3 cards same rank
        - 'triple_single': 3 same + 1 kicker
        - 'triple_pair': 3 same + 1 pair kicker
        - 'straight': 5+ consecutive singles (no 2 or jokers)
        - 'pair_straight': 3+ consecutive pairs (no 2 or jokers)
        - 'triple_straight': 2+ consecutive triples (no 2 or jokers)
        - 'triple_straight_single': 2+ consecutive triples each with 1 single kicker
        - 'triple_straight_pair': 2+ consecutive triples each with 1 pair kicker
        - 'four_two_single': 4 same + 2 different singles
        - 'four_two_pair': 4 same + 2 different pairs
        - 'bomb': 4 cards same rank
        - 'rocket': Black Joker + Red Joker
        """
        if not cards:
            return (None, None, None)

        n = len(cards)
        sorted_cards = sorted(cards, key=lambda c: c.get_rank_value())

        # Count rank frequencies
        rank_counts = {}
        for card in sorted_cards:
            rank_counts[card.rank] = rank_counts.get(card.rank, 0) + 1

        counts_list = sorted(rank_counts.items(), key=lambda x: (x[1], Card.ranks.index(x[0])), reverse=True)

        # Rocket: BJ + RJ
        if n == 2 and set(c.rank for c in sorted_cards) == {'BJ', 'RJ'}:
            return ('rocket', 999, 1)

        # Bomb: 4 of a kind
        if n == 4 and len(rank_counts) == 1:
            return ('bomb', Card.ranks.index(sorted_cards[0].rank), 1)

        # Single
        if n == 1:
            return ('single', Card.ranks.index(sorted_cards[0].rank), 1)

        # Pair
        if n == 2 and len(rank_counts) == 1:
            return ('pair', Card.ranks.index(sorted_cards[0].rank), 1)

        # Triple
        if n == 3 and len(rank_counts) == 1:
            return ('triple', Card.ranks.index(sorted_cards[0].rank), 1)

        # Triple + Single
        if n == 4 and len(rank_counts) == 2 and max(rank_counts.values()) == 3:
            triple_rank = counts_list[0][0]
            return ('triple_single', Card.ranks.index(triple_rank), 1)

        # Triple + Pair
        if n == 5 and len(rank_counts) == 2 and sorted(rank_counts.values()) == [2, 3]:
            triple_rank = counts_list[0][0]
            return ('triple_pair', Card.ranks.index(triple_rank), 1)

        # Straight: 5+ consecutive singles (no 2 or jokers)
        if n >= 5 and len(rank_counts) == n:
            values = [Card.ranks.index(card.rank) for card in sorted_cards]
            if all(v < 12 for v in values):  # No 2 (index 12) or jokers
                if all(values[i+1] - values[i] == 1 for i in range(len(values)-1)):
                    return ('straight', values[0], n)

        # Pair Straight: 3+ consecutive pairs
        if n >= 6 and n % 2 == 0 and all(c == 2 for c in rank_counts.values()):
            ranks = sorted([Card.ranks.index(r) for r in rank_counts.keys()])
            if all(v < 12 for v in ranks):  # No 2 or jokers
                if all(ranks[i+1] - ranks[i] == 1 for i in range(len(ranks)-1)):
                    return ('pair_straight', ranks[0], len(ranks))

        # Triple Straight: 2+ consecutive triples
        if n >= 6 and n % 3 == 0 and all(c == 3 for c in rank_counts.values()):
            ranks = sorted([Card.ranks.index(r) for r in rank_counts.keys()])
            if all(v < 12 for v in ranks):
                if all(ranks[i+1] - ranks[i] == 1 for i in range(len(ranks)-1)):
                    return ('triple_straight', ranks[0], len(ranks))

        # Triple Straight + Singles: (3+1) * N where N >= 2
        if n >= 8 and n % 4 == 0:
            num_sets = n // 4
            triples_counts = [k for k, v in rank_counts.items() if v == 3]
            if len(triples_counts) == num_sets:
                triple_values = sorted([Card.ranks.index(r) for r in triples_counts])
                if all(v < 12 for v in triple_values):
                    if all(triple_values[i+1] - triple_values[i] == 1 for i in range(len(triple_values)-1)):
                        return ('triple_straight_single', triple_values[0], num_sets)

        # Triple Straight + Pairs: (3+2) * N where N >= 2
        if n >= 10 and n % 5 == 0:
            num_sets = n // 5
            triples_counts = [k for k, v in rank_counts.items() if v == 3]
            pairs_counts = [k for k, v in rank_counts.items() if v == 2]
            if len(triples_counts) == num_sets and len(pairs_counts) == num_sets:
                triple_values = sorted([Card.ranks.index(r) for r in triples_counts])
                if all(v < 12 for v in triple_values):
                    if all(triple_values[i+1] - triple_values[i] == 1 for i in range(len(triple_values)-1)):
                        return ('triple_straight_pair', triple_values[0], num_sets)

        # Four + Two Singles
        if n == 6 and len([c for c in rank_counts.values() if c == 4]) == 1:
            four_rank = [k for k, v in rank_counts.items() if v == 4][0]
            return ('four_two_single', Card.ranks.index(four_rank), 1)

        # Four + Two Pairs
        if n == 8 and len([c for c in rank_counts.values() if c == 4]) == 1:
            pairs = [k for k, v in rank_counts.items() if v == 2]
            if len(pairs) == 2:
                four_rank = [k for k, v in rank_counts.items() if v == 4][0]
                return ('four_two_pair', Card.ranks.index(four_rank), 1)

        return (None, None, None)

    def can_beat(self, play_cards, last_cards):
        """
        Check if play_cards can beat last_cards.
        Returns: (True, combo_type, base_value, chain_length) or (False, None, None, None)
        """
        # Classify the play
        play_type, play_value, play_chain = self.classify_hand(play_cards)
        if play_type is None:
            return (False, None, None, None)

        # First play of a round (no last cards)
        if not last_cards:
            return (True, play_type, play_value, play_chain)

        # Classify last play
        last_type, last_value, last_chain = self.classify_hand(last_cards)

        # Rocket beats everything
        if play_type == 'rocket':
            return (True, play_type, play_value, play_chain)

        # Bomb beats everything except rocket and bigger bombs
        if play_type == 'bomb':
            if last_type == 'rocket':
                return (False, None, None, None)
            if last_type == 'bomb':
                return (play_value > last_value, play_type, play_value, play_chain) if play_value > last_value else (False, None, None, None)
            return (True, play_type, play_value, play_chain)

        # If last was bomb/rocket and play is not, can't beat
        if last_type in ['bomb', 'rocket']:
            return (False, None, None, None)

        # Same type: must have same chain length and higher value
        if play_type == last_type and play_chain == last_chain:
            if play_value > last_value:
                return (True, play_type, play_value, play_chain)

        return (False, None, None, None)

    def get_state(self):
        landlord_cards = []
        if self.landlord:
            landlord_cards = [card.to_dict() for card in self.landlord_cards]

        # Format last combo info for display
        last_combo_display = None
        if self.round_winner and self.last_combo_type:
            player_name = self.players.get(self.round_winner, {}).get('name', 'Unknown')
            combo_chain = getattr(self, 'last_combo_chain', None)
            combo_text = self.format_combo_display(self.last_combo_type, combo_chain)
            last_combo_display = f"{player_name} played: {combo_text}"

        return {
            'game_id': self.game_id,
            'players': {pid: {
                'name': info['name'],
                'hand_count': len(info['hand']),
                'score': info.get('score', 0),
                'is_landlord': pid == self.landlord,
                'has_passed': pid in self.passed_players,
                'connected': info.get('connected', True)
            } for pid, info in self.players.items()},
            'current_player': self.current_player,
            'landlord': self.landlord,
            'landlord_caller': self.landlord_caller,
            'status': self.status,
            'last_played': [card.to_dict() for card in self.last_played] if self.last_played else None,
            'round_winner': self.round_winner,
            'round_starter': self.round_starter,
            'bid_pool': self.bid_pool,
            'take_count': self.take_count,
            'landlord_cards': landlord_cards,
            'last_combo_display': last_combo_display,
            'winner': self.winner
        }

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

    # Check if there's a disconnected player slot available and take it
    disconnected_pid = None
    for pid, player_info in game.players.items():
        if not player_info.get('connected', True):
            disconnected_pid = pid
            break

    if disconnected_pid:
        # Rejoin as the disconnected player with new name
        player_id = disconnected_pid
        game.players[player_id]['name'] = player_name
        game.players[player_id]['connected'] = True
        game.last_heartbeat[player_id] = datetime.now().timestamp()
        return jsonify({
            'success': True,
            'player_id': player_id,
            'game_state': game.get_state()
        })

    # Check if game is full (3 connected players)
    connected_players = [pid for pid in game.players if game.players[pid].get('connected', True)]
    if len(connected_players) >= 3:
        return jsonify({'success': False, 'message': 'Game is full'}), 400

    player_id = str(uuid.uuid4())[:8]
    game.players[player_id] = {
        'name': player_name,
        'hand': [],
        'score': 0,
        'landlord_cards': [],
        'connected': True
    }
    game.last_heartbeat[player_id] = datetime.now().timestamp()
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

    # Validate that the requesting player is the current player
    if game.current_player != player_id:
        return jsonify({'success': False, 'message': 'Not your turn'}), 400

    player_ids = list(game.players.keys())
    current_idx = player_ids.index(game.current_player)

    # If player already passed, just skip them
    if player_id in game.passed_players:
        game.current_player = player_ids[(current_idx + 1) % len(player_ids)]

    elif action == 'call':
        # Remove player from passed list when they take action
        game.passed_players.discard(player_id)
        # First person to call for landlord
        game.landlord_caller = player_id
        game.bid_pool = 1
        game.take_count = 0
        game.current_player = player_ids[(current_idx + 1) % len(player_ids)]

    elif action == 'take':
        # Remove player from passed list when they take action
        game.passed_players.discard(player_id)
        # Someone taking the landlord position (bid doubles, take_count increments)
        if game.take_count < 2:  # Max 2 takes
            game.landlord_caller = player_id
            game.bid_pool *= 2
            game.take_count += 1
            game.current_player = player_ids[(current_idx + 1) % len(player_ids)]

    elif action == 'pass':
        # Player passes - add them to passed_players set
        game.passed_players.add(player_id)
        game.current_player = player_ids[(current_idx + 1) % len(player_ids)]

    # Check if bidding is done (2+ passes and landlord determined)
    if game.landlord_caller and len(game.passed_players) >= 2:
        game.status = 'playing'
        game.landlord = game.landlord_caller
        game.current_player = game.landlord_caller
        # Add landlord cards to landlord's hand
        game.players[game.landlord]['hand'].extend(game.landlord_cards)
        game.passed_players = set()
    # Check if everyone passed with no one calling (3 passes = reshuffle)
    elif len(game.passed_players) >= 3 and not game.landlord_caller:
        # Everyone passed, no one called - reshuffle and restart bidding
        game.deal_cards()
        game.current_player = list(game.players.keys())[0]
        game.bid_pool = 1
        game.take_count = 0
        game.landlord = None
        game.landlord_caller = None
        game.passed_players = set()

    return jsonify(game.get_state())

@app.route('/api/play_cards', methods=['POST'])
def play_cards():
    data = request.json
    game_id = data['game_id']
    player_id = data['player_id']
    cards_data = data.get('cards', [])  # Empty means pass

    game = games[game_id]

    # Validate that the requesting player is the current player
    if game.current_player != player_id:
        return jsonify({'success': False, 'message': 'Not your turn'}), 400

    if not cards_data:
        # Player passes
        # Check if this is the first play of the round (no cards have been played)
        if not game.round_starter:
            # This is the first play, cannot pass
            return jsonify({
                'success': False,
                'message': 'Cannot pass on your turn to start a combo'
            }), 400

        # Player passes - add to passed_players set
        game.passed_players.add(player_id)

        player_ids = list(game.players.keys())
        current_idx = player_ids.index(game.current_player)
        next_player = player_ids[(current_idx + 1) % len(player_ids)]

        # If 2 players have passed (other 2 players after round winner), round resets
        if len(game.passed_players) >= 2:
            # Round winner plays again, reset combo tracking
            game.current_player = game.round_winner
            game.last_played = None
            game.last_combo_type = None
            game.last_combo_value = None
            game.last_combo_chain = None
            game.round_starter = None  # Reset for new round
            game.passed_players = set()  # Clear pass tracking for new round
        else:
            game.current_player = next_player
    else:
        # Convert card data to Card objects for validation
        play_cards = [Card(card_data['rank'], card_data['suit']) for card_data in cards_data]

        # Validate the play
        can_play, combo_type, combo_value, combo_chain = game.can_beat(play_cards, game.last_played)

        if not can_play:
            return jsonify({
                'success': False,
                'message': 'Invalid play'
            }), 400

        # Valid play - remove cards from hand
        hand = game.players[player_id]['hand']
        for card in play_cards:
            # Find and remove the card from hand
            hand = [c for c in hand if not (c.rank == card.rank and c.suit == card.suit)]
        game.players[player_id]['hand'] = hand

        # Store last played cards and combo info
        game.last_played = play_cards
        game.last_combo_type = combo_type
        game.last_combo_value = combo_value
        game.last_combo_chain = combo_chain
        game.round_winner = player_id

        # Set round starter if this is the first play
        if not game.round_starter:
            game.round_starter = player_id

        game.passed_players = set()  # Clear pass tracking since someone played

        # Move to next player in join order
        player_ids = list(game.players.keys())
        current_idx = player_ids.index(player_id)
        game.current_player = player_ids[(current_idx + 1) % len(player_ids)]

        # Check win condition
        if len(hand) == 0:
            game.status = 'finished'
            game.winner = player_id

            if player_id == game.landlord:
                # Landlord wins: gains points equal to bid pool from each player
                game.players[player_id]['score'] += game.bid_pool * 2
                # Each other player loses bid pool points
                for pid in game.players:
                    if pid != player_id:
                        game.players[pid]['score'] -= game.bid_pool
            else:
                # Non-landlord wins: ALL peasants gain bid pool from landlord
                for pid in game.players:
                    if pid != game.landlord:
                        game.players[pid]['score'] += game.bid_pool
                # Landlord loses bid pool to each peasant
                game.players[game.landlord]['score'] -= game.bid_pool * 2
            game.round_starter = None

    return jsonify(game.get_state())

if __name__ == '__main__':
    app.run(debug=True)
