import random
from datetime import datetime


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
        self.bots = {}  # player_id -> Bot instance for bot players
        self.bot_disconnect_timers = {}  # player_id -> timestamp when they disconnected (for spawning bots)

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
                'is_bot': info.get('is_bot', False),
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

    # ==================== Game Action Methods ====================

    def join_player(self, player_name):
        """
        Join a player to the game.
        Returns: (success, player_id, error_message)
        """
        import uuid
        
        # Check if there's a disconnected player slot available and take it
        disconnected_pid = None
        for pid, player_info in self.players.items():
            if not player_info.get('connected', True):
                disconnected_pid = pid
                break

        if disconnected_pid:
            # Rejoin as the disconnected player with new name
            player_id = disconnected_pid
            self.players[player_id]['name'] = player_name
            self.players[player_id]['connected'] = True
            self.last_heartbeat[player_id] = datetime.now().timestamp()
            return (True, player_id, None)

        # Check if game is full (3 connected players)
        connected_players = [pid for pid in self.players if self.players[pid].get('connected', True)]
        if len(connected_players) >= 3:
            return (False, None, 'Game is full')

        player_id = str(uuid.uuid4())[:8]
        self.players[player_id] = {
            'name': player_name,
            'hand': [],
            'score': 0,
            'landlord_cards': [],
            'connected': True
        }
        self.last_heartbeat[player_id] = datetime.now().timestamp()
        return (True, player_id, None)

    def create_bot_player(self):
        """
        Create and add a bot player to the game.
        Returns: player_id of the bot, or None if game is full
        """
        from bot import Bot
        import uuid
        
        # Check if game is at capacity
        connected_players = [pid for pid in self.players if self.players[pid].get('connected', True)]
        if len(connected_players) >= 3:
            return None
        
        # Create bot with unique ID
        player_id = f"bot_{str(uuid.uuid4())[:6]}"
        bot = Bot(player_id)
        
        # Add bot to game
        self.players[player_id] = {
            'name': bot.name,
            'hand': [],
            'score': 0,
            'is_bot': True,
            'connected': True
        }
        self.bots[player_id] = bot
        self.last_heartbeat[player_id] = datetime.now().timestamp()
        
        return player_id

    def replace_bot_with_player(self, player_name):
        """
        Replace a bot player with a real player joining.
        Returns: (success, player_id, error_message)
        """
        import uuid
        
        # Find a bot player to replace
        bot_to_replace = None
        for pid, player_info in self.players.items():
            if player_info.get('is_bot', False) and player_info.get('connected', True):
                bot_to_replace = pid
                break
        
        if not bot_to_replace:
            return (False, None, 'No bot available to replace')
        
        # Remove the bot and reuse the slot
        new_player_id = str(uuid.uuid4())[:8]
        bot_hand = self.players[bot_to_replace]['hand'].copy()
        bot_score = self.players[bot_to_replace].get('score', 0)
        
        # Remove bot from tracking
        del self.bots[bot_to_replace]
        del self.players[bot_to_replace]
        
        # Add new player with bot's slot
        self.players[new_player_id] = {
            'name': player_name,
            'hand': bot_hand,
            'score': bot_score,
            'is_bot': False,
            'connected': True
        }
        self.last_heartbeat[new_player_id] = datetime.now().timestamp()
        
        # If the bot was the current player or landlord, update references
        if self.current_player == bot_to_replace:
            self.current_player = new_player_id
        if self.landlord == bot_to_replace:
            self.landlord = new_player_id
        if self.round_winner == bot_to_replace:
            self.round_winner = new_player_id
        if self.landlord_caller == bot_to_replace:
            self.landlord_caller = new_player_id
        
        # Update passed_players set
        if bot_to_replace in self.passed_players:
            self.passed_players.discard(bot_to_replace)
            self.passed_players.add(new_player_id)
        
        return (True, new_player_id, None)

    def get_eligible_bot_players(self):
        """
        Get list of bot player IDs that are currently in the game.
        Returns: list of bot player IDs
        """
        return [pid for pid in self.bots.keys()]

    def check_and_spawn_bots(self, timeout_seconds=10):
        """
        Check for disconnected players and spawn bots if they haven't reconnected.
        Args:
            timeout_seconds: Time in seconds before spawning a bot for a disconnected player
        """
        current_time = datetime.now().timestamp()
        
        # Check for disconnected players
        for pid, player_info in list(self.players.items()):
            if not player_info.get('connected', True) and not player_info.get('is_bot', False):
                # Player is disconnected
                if pid not in self.bot_disconnect_timers:
                    # Start the timeout timer
                    self.bot_disconnect_timers[pid] = current_time
                elif current_time - self.bot_disconnect_timers[pid] >= timeout_seconds:
                    # Timeout reached - spawn a bot to replace them
                    last_heartbeat = self.last_heartbeat.get(pid, 0)
                    player_name = player_info.get('name', 'Player')
                    
                    # Create bot to replace disconnected player
                    from bot import Bot
                    import uuid
                    
                    bot_player_id = f"bot_{str(uuid.uuid4())[:6]}"
                    bot = Bot(bot_player_id, f"Bot ({player_name})")
                    
                    # Replace the disconnected player with bot
                    bot_hand = self.players[pid]['hand'].copy() if self.players[pid].get('hand') else []
                    bot_score = self.players[pid].get('score', 0)
                    
                    del self.players[pid]
                    
                    self.players[bot_player_id] = {
                        'name': bot.name,
                        'hand': bot_hand,
                        'score': bot_score,
                        'is_bot': True,
                        'connected': True
                    }
                    self.bots[bot_player_id] = bot
                    self.last_heartbeat[bot_player_id] = current_time
                    
                    # Update game references
                    if self.current_player == pid:
                        self.current_player = bot_player_id
                    if self.landlord == pid:
                        self.landlord = bot_player_id
                    if self.round_winner == pid:
                        self.round_winner = bot_player_id
                    if self.landlord_caller == pid:
                        self.landlord_caller = bot_player_id
                    
                    # Update passed_players set
                    if pid in self.passed_players:
                        self.passed_players.discard(pid)
                        self.passed_players.add(bot_player_id)
                    
                    # Remove the disconnect timer
                    del self.bot_disconnect_timers[pid]

    def bid_landlord(self, player_id, action):
        """
        Handle landlord bidding action.
        Args:
            player_id: The player making the bid
            action: 'call', 'take', or 'pass'
        Returns: (success, error_message)
        """
        # Validate that the requesting player is the current player
        if self.current_player != player_id:
            return (False, 'Not your turn')

        player_ids = list(self.players.keys())
        current_idx = player_ids.index(self.current_player)

        # If player already passed, just skip them
        if player_id in self.passed_players:
            self.current_player = player_ids[(current_idx + 1) % len(player_ids)]
            return (True, None)

        if action == 'call':
            # Remove player from passed list when they take action
            self.passed_players.discard(player_id)
            # First person to call for landlord
            self.landlord_caller = player_id
            self.bid_pool = 1
            self.take_count = 0
            self.current_player = player_ids[(current_idx + 1) % len(player_ids)]

        elif action == 'take':
            # Remove player from passed list when they take action
            self.passed_players.discard(player_id)
            # Someone taking the landlord position (bid doubles, take_count increments)
            if self.take_count < 2:  # Max 2 takes
                self.landlord_caller = player_id
                self.bid_pool *= 2
                self.take_count += 1
                self.current_player = player_ids[(current_idx + 1) % len(player_ids)]

        elif action == 'pass':
            # Player passes - add them to passed_players set
            self.passed_players.add(player_id)
            self.current_player = player_ids[(current_idx + 1) % len(player_ids)]

        # Check if bidding is done (2+ passes and landlord determined)
        if self.landlord_caller and len(self.passed_players) >= 2:
            self.status = 'playing'
            self.landlord = self.landlord_caller
            self.current_player = self.landlord_caller
            # Add landlord cards to landlord's hand
            self.players[self.landlord]['hand'].extend(self.landlord_cards)
            self.passed_players = set()
        # Check if everyone passed with no one calling (3 passes = reshuffle)
        elif len(self.passed_players) >= 3 and not self.landlord_caller:
            # Everyone passed, no one called - reshuffle and restart bidding
            self.deal_cards()
            self.current_player = list(self.players.keys())[0]
            self.bid_pool = 1
            self.take_count = 0
            self.landlord = None
            self.landlord_caller = None
            self.passed_players = set()

        return (True, None)

    def play_cards(self, player_id, cards_data):
        """
        Handle card playing action.
        Args:
            player_id: The player playing the cards
            cards_data: List of card dicts [{rank, suit}] or empty list to pass
        Returns: (success, error_message)
        """
        # Validate that the requesting player is the current player
        if self.current_player != player_id:
            return (False, 'Not your turn')

        if not cards_data:
            # Player passes
            # Check if this is the first play of the round (no cards have been played)
            if not self.round_starter:
                # This is the first play, cannot pass
                return (False, 'Cannot pass on your turn to start a combo')

            # Player passes - add to passed_players set
            self.passed_players.add(player_id)

            player_ids = list(self.players.keys())
            current_idx = player_ids.index(self.current_player)
            next_player = player_ids[(current_idx + 1) % len(player_ids)]

            # If 2 players have passed (other 2 players after round winner), round resets
            if len(self.passed_players) >= 2:
                # Round winner plays again, reset combo tracking
                self.current_player = self.round_winner
                self.last_played = None
                self.last_combo_type = None
                self.last_combo_value = None
                self.last_combo_chain = None
                self.round_starter = None  # Reset for new round
                self.passed_players = set()  # Clear pass tracking for new round
            else:
                self.current_player = next_player
        else:
            # Convert card data to Card objects for validation
            play_cards = [Card(card_data['rank'], card_data['suit']) for card_data in cards_data]

            # Validate the play
            can_play, combo_type, combo_value, combo_chain = self.can_beat(play_cards, self.last_played)

            if not can_play:
                return (False, 'Invalid play')

            # Valid play - remove cards from hand
            hand = self.players[player_id]['hand']
            for card in play_cards:
                # Find and remove the card from hand
                hand = [c for c in hand if not (c.rank == card.rank and c.suit == card.suit)]
            self.players[player_id]['hand'] = hand

            # Store last played cards and combo info
            self.last_played = play_cards
            self.last_combo_type = combo_type
            self.last_combo_value = combo_value
            self.last_combo_chain = combo_chain
            self.round_winner = player_id

            # Set round starter if this is the first play
            if not self.round_starter:
                self.round_starter = player_id

            self.passed_players = set()  # Clear pass tracking since someone played

            # Move to next player in join order
            player_ids = list(self.players.keys())
            current_idx = player_ids.index(player_id)
            self.current_player = player_ids[(current_idx + 1) % len(player_ids)]

            # Check win condition
            if len(hand) == 0:
                self.status = 'finished'
                self.winner = player_id

                if player_id == self.landlord:
                    # Landlord wins: gains points equal to bid pool from each player
                    self.players[player_id]['score'] += self.bid_pool * 2
                    # Each other player loses bid pool points
                    for pid in self.players:
                        if pid != player_id:
                            self.players[pid]['score'] -= self.bid_pool
                else:
                    # Non-landlord wins: ALL peasants gain bid pool from landlord
                    for pid in self.players:
                        if pid != self.landlord:
                            self.players[pid]['score'] += self.bid_pool
                    # Landlord loses bid pool to each peasant
                    self.players[self.landlord]['score'] -= self.bid_pool * 2
                self.round_starter = None

        return (True, None)
