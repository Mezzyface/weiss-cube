"""
Full translation + normalization pass.

For JP cards  : retranslate card_text_en from card_text_jp_raw using:
                1. Learned phrase map (from aligned EN/JP card pairs)
                2. Comprehensive hand-crafted JP→EN phrase table
                3. Post-processing normalizations

For EN cards  : re-normalize card_text_en from card_text_en_raw using:
                1. Fullwidth→halfwidth conversion
                2. Term standardisation (Library→deck, CX COMBO, etc.)

Reads raw columns as source-of-truth so this script is idempotent.

Usage:
    python translate_normalize.py [--dry-run]
"""
import sqlite3, sys, re, json
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

DB_PATH  = Path('weiss_cards.db')
KEY_PATH = Path('data/translation_key.json')

DRY_RUN = '--dry-run' in sys.argv

# ── Load learned translation key ─────────────────────────────────────────────

if not KEY_PATH.exists():
    print('ERROR: data/translation_key.json not found. Run build_translation_key.py first.')
    sys.exit(1)

_key = json.loads(KEY_PATH.read_text(encoding='utf-8'))
LEARNED: dict[str, str] = _key['phrase_map']   # 9,856 pairs
print(f'Learned phrase pairs loaded: {len(LEARNED):,}')

# Pre-sort by descending length so longer matches win
LEARNED_SORTED = sorted(LEARNED.items(), key=lambda x: -len(x[0]))


# ── Comprehensive JP→EN phrase table ─────────────────────────────────────────
# Order matters: longest / most specific entries first within each group.

JP_MAP: list[tuple[str, str]] = [

    # ── Ability markers ───────────────────────────────────────────────────────
    ('【自】',       '[AUTO] '),
    ('【永】',       '[CONT] '),
    ('【起】',       '[ACT] '),
    ('【カウンター】', '[COUNTER] '),
    ('【CXコンボ】', 'CX COMBO '),

    # ── Full opening sentences (most specific → most general) ─────────────────
    ('このカードが手札から舞台に置かれた時、あなたはコストを払ってよい。そうしたら、あなたは自分の',
     'when this card is placed on the stage from your hand, you may pay the cost. If you do, choose 1 of your '),
    ('このカードが手札から舞台に置かれた時、あなたは自分の',
     'when this card is placed on the stage from your hand, choose 1 of your '),
    ('このカードが手札から舞台に置かれた時、',
     'when this card is placed on the stage from your hand, '),
    ('このカードが手札から舞台に置かれた時',
     'when this card is placed on the stage from your hand'),
    ('このカードが舞台から控え室に置かれた時、あなたはコストを払ってよい。そうしたら、あなたは自分の',
     'when this card is placed in the waiting room from the stage, you may pay the cost. If you do, choose 1 of your '),
    ('このカードが舞台から控え室に置かれた時、',
     'when this card is placed in the waiting room from the stage, '),
    ('このカードが舞台から控え室に置かれた時',
     'when this card is placed in the waiting room from the stage'),
    ('このカードがアタックした時、クライマックス置場に',
     'when this card attacks, if '),
    ('このカードがアタックした時、あなたはコストを払ってよい。そうしたら、あなたは自分の',
     'when this card attacks, you may pay the cost. If you do, choose 1 of your '),
    ('このカードがアタックした時、あなたは自分の',
     'when this card attacks, choose 1 of your '),
    ('このカードがアタックした時、',
     'when this card attacks, '),
    ('このカードがアタックした時',
     'when this card attacks'),
    ('このカードがバトル相手にリバースされた時、',
     'when this card is reversed by the battle opponent, '),
    ('バトル相手が【リバース】した時、',
     'when the battle opponent becomes reversed, '),
    ('このカードの正面のキャラの',
     "the character opposite this card's "),

    # ── Placed on stage ───────────────────────────────────────────────────────
    ('手札から舞台に置かれた時、あなたはコストを払ってよい。そうしたら、あなたは自分の',
     'is placed on the stage from your hand, you may pay the cost. If you do, choose 1 of your '),
    ('手札から舞台に置かれた時、あなたは自分の',
     'is placed on the stage from your hand, choose 1 of your '),
    ('手札から舞台に置かれた時、', 'is placed on the stage from your hand, '),
    ('手札から舞台に置かれた時',   'is placed on the stage from your hand'),
    ('舞台の好きな枠に【レスト】して置く', 'place it rested in any slot on the stage'),
    ('舞台の好きな枠に置く',       'place it in any slot on the stage'),
    ('舞台に【レスト】して置く',   'place it rested on the stage'),
    ('舞台に置かれた時、',         'is placed on the stage, '),
    ('舞台に置かれた時',           'is placed on the stage'),
    ('舞台に置く',                 'place it on the stage'),
    ('舞台から',                   'from the stage'),
    ('舞台の',                     'on the stage '),
    ('舞台に',                     'to the stage'),

    # ── Cost payment ──────────────────────────────────────────────────────────
    ('あなたはコストを払ってよい。そうしたら、あなたは自分の',
     'you may pay the cost. If you do, choose 1 of your '),
    ('あなたはコストを払ってよい。そうしたら、',
     'you may pay the cost. If you do, '),
    ('あなたはコストを払ってよい',  'you may pay the cost'),
    ('そうしたら、あなたは自分の',  'if you do, choose 1 of your '),
    ('そうしたら、',                'if you do, '),
    ('コストを払ってよい',          'you may pay the cost'),

    # ── Waiting room ──────────────────────────────────────────────────────────
    ('控え室に置かれた時、あなたはコストを払ってよい。そうしたら、',
     'in the waiting room, you may pay the cost. If you do, '),
    ('控え室に置かれた時、',        'when placed in the waiting room, '),
    ('控え室に置かれた時',          'when placed in the waiting room'),
    ('控え室のトリガーアイコンにがあるキャラを',
     'character with a trigger icon in your waiting room'),
    ('控え室のレベルＸ以下の',      'level X or lower card in your waiting room'),
    ('控え室のクライマックスを',    'climax in your waiting room'),
    ('自分の控え室の',              'your waiting room '),
    ('自分の控え室から',            'from your waiting room '),
    ('控え室に置いてよい）',        'you may put it in the waiting room)'),
    ('控え室に置いてよい',          'you may put it in the waiting room'),
    ('控え室に置き、',              'put it in the waiting room, '),
    ('控え室に置く。',              'put it in the waiting room.'),
    ('控え室に置く',                'put it in the waiting room'),
    ('控え室の',                    'in the waiting room '),
    ('控え室に',                    'to the waiting room'),
    ('控え室から',                  'from the waiting room'),

    # ── Hand ──────────────────────────────────────────────────────────────────
    ('手札のこのカードのレベルを－', 'this card in your hand gets -'),
    ('手札のこのカードのレベルを＋', 'this card in your hand gets +'),
    ('手札のこのカードを',          'this card from your hand'),
    ('手札のクライマックスを',      'climax from your hand'),
    ('手札のキャラを',              'character from your hand'),
    ('手札から',                    'from your hand'),
    ('手札に戻すか',                'return it to your hand or'),
    ('手札に戻してよい）',          'you may return it to your hand)'),
    ('手札に戻してよい',            'you may return it to your hand'),
    ('手札に戻し、',                'return it to your hand, '),
    ('手札に戻す。',                'return it to your hand.'),
    ('手札に戻す',                  'return it to your hand'),
    ('手札に加え、残りのカードを',  'add it to your hand, put the rest in the '),
    ('手札に加え、',                'add it to your hand, '),
    ('手札に加える',                'add it to your hand'),
    ('手札に加え',                  'add it to your hand'),
    ('手札を1枚',                   '1 card from your hand'),
    ('手札の',                      'from your hand '),
    ('手札に',                      'to your hand'),
    ('手札を',                      'your hand'),

    # ── Deck ──────────────────────────────────────────────────────────────────
    ('山札の上から',                'from the top of your deck'),
    ('山札の上に置いてよい',        'you may put it on top of your deck'),
    ('山札の上に置く',              'put it on top of your deck'),
    ('山札を上から',                'flip over the top of your deck,'),
    ('山札をシャッフルする。',      'shuffle your deck.'),
    ('山札をシャッフルする',        'shuffle your deck'),
    ('山札に戻し、',                'return it to your deck, '),
    ('山札に戻す',                  'return it to your deck'),
    ('山札を見て',                  'look at your deck'),
    ('自分の山札の',                'your deck '),
    ('山札の',                      'of your deck '),
    ('山札に',                      'into your deck'),
    ('山札を',                      'your deck'),

    # ── Stock ─────────────────────────────────────────────────────────────────
    ('ストック置場に置いてよい',    'you may put it in your stock'),
    ('ストック置場に置く',          'put it in your stock'),
    ('ストック置場に',              'in your stock'),
    ('ストック置場から',            'from your stock'),
    ('ストック置場',                'your stock'),
    ('自分のストックを',            'your stock'),
    ('ストックに置く',              'put it in your stock'),
    ('ストックに',                  'into your stock'),

    # ── Clock ─────────────────────────────────────────────────────────────────
    ('クロックの上から',            'from the top of your clock'),
    ('クロック置場に置く',          'put it in your clock'),
    ('クロック置場に',              'in your clock'),
    ('クロック置場',                'your clock'),
    ('自分のクロックの',            'your clock '),
    ('クロックに置く',              'put it in your clock'),
    ('クロックに',                  'into your clock'),
    ('クロックから',                'from your clock'),
    ('クロックの',                  'of your clock '),

    # ── Memory ────────────────────────────────────────────────────────────────
    ('思い出にする',                'send it to memory'),
    ('思い出に置く',                'put it in memory'),
    ('自分の思い出の',              'in your memory '),
    ('思い出に',                    'to memory'),
    ('思い出から',                  'from memory'),
    ('思い出の',                    'in memory '),
    ('思い出',                      'memory'),

    # ── Climax zone ───────────────────────────────────────────────────────────
    ('クライマックス置場に',        'in the climax area'),
    ('クライマックス置場から',      'from the climax area'),
    ('クライマックス置場の',        'of the climax area '),
    ('クライマックス置場',          'climax area'),

    # ── Action phrases ────────────────────────────────────────────────────────
    ('【レスト】して置く',          'place it as [REST]'),
    ('【レスト】する',              '[REST] it'),
    ('【スタンド】する',            '[STAND] it'),
    ('【リバース】する',            '[REVERSE] it'),
    ('【レスト】している',          '[REST]ed'),
    ('【スタンド】している',        '[STAND]ing'),
    ('【リバース】した時、',        'when reversed, '),
    ('【リバース】した時',          'when reversed'),
    ('【リバース】',                '[REVERSE]'),
    ('【レスト】',                  '[REST]'),
    ('【スタンド】',                '[STAND]'),
    ('アンコール',                  'ENCORE'),
    ('集中',                        'BRAINSTORM'),

    # ── Character references ──────────────────────────────────────────────────
    ('あなたのキャラすべてに、パワーを＋', 'all of your characters get +'),
    ('他のあなたのキャラすべてに、パワーを＋', 'all of your other characters get +'),
    ('他のあなたのキャラすべてに、', 'all of your other characters '),
    ('あなたのキャラすべてに、',    'all of your characters '),
    ('::TRAIT::のキャラを1枚選び、', 'choose 1 of your ::TRAIT:: characters, '),
    ('::TRAIT::のキャラが4枚以上なら、', 'if you have 4 or more ::TRAIT:: characters, '),
    ('::TRAIT::のキャラが3枚以上なら、', 'if you have 3 or more ::TRAIT:: characters, '),
    ('::TRAIT::のキャラが2枚以上なら、', 'if you have 2 or more ::TRAIT:: characters, '),
    ('::TRAIT::のキャラすべてに、', 'all of your ::TRAIT:: characters '),
    ('::TRAIT::のキャラ1枚につき、このカードのパワーを＋',
     'for each of your ::TRAIT:: characters, this card gets +'),
    ('::TRAIT::のキャラが',         '::TRAIT:: characters '),
    ('::TRAIT::のキャラを',         '::TRAIT:: character '),
    ('::TRAIT::のキャラ',           '::TRAIT:: character'),
    ('のキャラを1枚まで選んで相手に見せ、',
     'choose up to 1 character, reveal it to your opponent, '),
    ('のキャラを1枚選び、',         ' character, '),
    ('のキャラすべてに、',          ' characters, '),
    ('のキャラすべてに',            ' characters'),
    ('のキャラが',                  ' characters'),
    ('のキャラを',                  ' character'),
    ('のキャラ',                    ' character'),

    # ── Targeting ─────────────────────────────────────────────────────────────
    ('あなたは自分の',              'choose 1 of your '),
    ('あなたは相手のキャラを1枚選び、', "choose 1 of your opponent's characters, "),
    ('あなたは相手の前列のキャラを1枚選び、', "choose 1 of your opponent's front row characters, "),
    ('あなたは相手の',              "choose 1 of your opponent's "),
    ('他のあなたの',                'your other '),
    ('あなたの',                    'your '),
    ('あなたは',                    'you '),
    ('相手の',                      "your opponent's "),

    # ── Power / soul ──────────────────────────────────────────────────────────
    ('パワーを＋',                  '+'),
    ('パワーを－',                  '-'),
    ('し、ソウルを＋',              ' power and +'),
    ('ソウルを＋',                  '+'),
    ('ソウルを－',                  '-'),
    ('レベルを－',                  'level -'),
    ('レベルを＋',                  'level +'),
    ('パワー',                      ' power'),
    ('ソウル',                      ' soul'),

    # ── Counting ──────────────────────────────────────────────────────────────
    ('枚以上なら、このカードのパワーを＋', ' or more, this card gets +'),
    ('枚以上なら、',                ' or more, '),
    ('枚以上',                      ' or more'),
    ('枚以下',                      ' or less'),
    ('枚まで選び、',                ' choose up to, '),
    ('枚まで選んで相手に見せ、',    ' choose up to, reveal to your opponent, '),
    ('枚まで見て、カードを',        ' cards, choose '),
    ('枚まで見て、',                ' cards from the top, '),
    ('枚選び、',                    ' choose, '),
    ('枚をめくり、',                ' cards, '),
    ('枚を、',                      ' cards, '),
    ('枚を',                        ' cards'),
    ('枚につき、このカードのパワーを＋', ' characters, this card gets +'),
    ('枚につき、',                  ' per '),
    ('1枚を',                       '1 card'),
    ('ターンにつき1回',             'once per turn'),
    ('ターンにつき',                'per turn'),

    # ── Timing ────────────────────────────────────────────────────────────────
    ('この能力は1ターンにつき1回まで発動する',
     'this ability activates up to once per turn'),
    ('この能力は',                  'this ability '),
    ('あなたのターン中、',          'during your turn, '),
    ('相手のターン中、',            "during your opponent's turn, "),
    ('そのターン中、',              'for the turn, '),
    ('ターンの終わりに、',          'at the end of the turn, '),
    ('ターンの終わりに',            'at the end of the turn'),
    ('次の相手のターンの終わりまで、', "until the end of your opponent's next turn, "),
    ('次の相手のターンの終わりまで', "until the end of your opponent's next turn"),

    # ── Trigger reminder text ─────────────────────────────────────────────────
    ('（ダメージキャンセルは発生する）', '(Damage may be canceled)'),
    ('ダメージキャンセルは発生する', 'Damage may be canceled'),
    ('（：このカードがトリガーした時、あなたは自分の',
     '(: When this card triggers, choose 1 of your '),
    ('（：このカードがトリガーした時、',
     '(: When this card triggers, '),

    # ── Stage positions ───────────────────────────────────────────────────────
    ('前列中央の枠',                'the center stage slot'),
    ('前列に',                      'in the front row'),
    ('前列の',                      "the front row's "),
    ('前列',                        'front row'),
    ('後列に',                      'in the back row'),
    ('後列の',                      "the back row's "),
    ('後列',                        'back row'),

    # ── Ability granting ──────────────────────────────────────────────────────
    ('は次の能力を得る。「',         'gains the following ability. "'),
    ('次の能力を得る。「',           'gains the following ability. "'),
    ('は次の能力を得る。『',         'gains the following ability. "'),
    ('次の能力を得る。『',           'gains the following ability. "'),
    ('は次の能力を与える。「',       'give it the following ability. "'),
    ('次の能力を与える。「',         'give it the following ability. "'),
    ('は次の能力を与える。『',       'give it the following ability. "'),
    ('次の能力を与える。『',         'give it the following ability. "'),
    ('次の能力を得る',               'gains the following ability'),
    ('次の2つの能力を得る',          'gains the following 2 abilities'),

    # ── Phase markers ─────────────────────────────────────────────────────────
    ('クライマックスフェイズの始めに、', 'at the start of your climax phase, '),
    ('アタックフェイズの始めに、',    'at the start of your attack phase, '),
    ('アンコールステップの始めに、',  'at the start of your encore step, '),
    ('ドローフェイズの始めに、',      'at the start of your draw phase, '),
    ('ターンの終わりまで、',          'until the end of the turn, '),
    ('ターンの終わりまで',            'until the end of the turn'),

    # ── Attack types ──────────────────────────────────────────────────────────
    ('フロントアタックされているキャラを', 'the front attacked character '),
    ('フロントアタックされている',    'being front attacked '),
    ('フロントアタックする',          'front attack'),
    ('フロントアタック',              'front attack'),
    ('サイドアタック',                'side attack'),
    ('ダイレクトアタック',            'direct attack'),
    ('アタックする',                  'attack'),

    # ── BACKUP ────────────────────────────────────────────────────────────────
    ('助太刀』を使った時、',          'when you use the BACKUP of this, '),
    ('助太刀』を使った時',            'when you use the BACKUP of this'),
    ('助太刀』',                      'BACKUP'),

    # ── Slot references ───────────────────────────────────────────────────────
    ('がいた枠に',                    'in the slot where it was '),
    ('がいた枠',                      'the slot where it was'),
    ('の枠に',                        ' slot '),
    ('の枠',                          ' slot'),

    # ── Conditional patterns ──────────────────────────────────────────────────
    ('レベルが',                      'level '),
    ('以上なら、',                    ' or more, '),
    ('以下なら、',                    ' or fewer, '),
    ('いるなら、',                    ' exists, '),
    ('があるなら、',                  ' exists, '),
    ('がいるなら',                    ' exists'),
    ('なら、',                        ', if so, '),
    ('なら',                          ' if so'),

    # ── Climax references ─────────────────────────────────────────────────────
    ('それらのカードのクライマックス1枚につき、', 'for each climax among those cards, '),
    ('それらのカードのクライマックス', 'the climax among those cards'),
    ('クライマックスが',              'climax '),
    ('クライマックスを',              'climax '),

    # ── Stock references ──────────────────────────────────────────────────────
    ('ストックの上から',              'from the top of your stock '),
    ('ストックの上に置く',            'put it on top of your stock'),

    # ── "in front of" / adjacent ─────────────────────────────────────────────
    ('前のあなたのキャラすべてに、', 'characters in front of this '),
    ('前のあなたのキャラ',           'characters in front of this'),
    ('正面のキャラの',               "the character opposite this card's "),
    ('正面のキャラ',                 'the character opposite this card'),
    ('前の',                         'in front of this '),

    # ── WS keywords ───────────────────────────────────────────────────────────
    ('チェンジ',                      'CHANGE'),
    ('絆',                            'BOND'),
    ('経験',                          'EXPERIENCE'),
    ('記憶',                          'RECOLLECTION'),
    ('プレイされて舞台に置かれた時',  'is placed on the stage'),
    ('プレイできない',                'cannot be played'),
    ('がプレイされて',                'when played '),

    # ── Color names ───────────────────────────────────────────────────────────
    ('赤のキャラ',                    'Red character'),
    ('青のキャラ',                    'Blue character'),
    ('緑のキャラ',                    'Green character'),
    ('黄のキャラ',                    'Yellow character'),
    ('紫のキャラ',                    'Purple character'),
    ('赤い',                          'Red '),
    ('青い',                          'Blue '),
    ('赤',                            'Red '),
    ('青',                            'Blue '),
    ('緑',                            'Green '),
    ('黄',                            'Yellow '),
    ('紫',                            'Purple '),

    # ── X value phrases ───────────────────────────────────────────────────────
    ('Ｘはあなたの',                  'X is equal to your '),
    ('Ｘは',                          'X is '),
    ('Xはあなたの',                   'X is equal to your '),
    ('Xは',                           'X is '),
    ('のカードのレベルの合計が',      ', if the total level of cards in the '),

    # ── Damage dealing ────────────────────────────────────────────────────────
    ('ダメージを与える。',            'deal damage to your opponent.'),
    ('ダメージを与え',                'deal damage to your opponent'),
    ('Ｘダメージ',                    'X damage'),

    # ── Misc game terms ───────────────────────────────────────────────────────
    ('元に戻す',                      'return it to its original place'),
    ('そうでない',                    'otherwise'),
    ('バトル中の',                    'in battle '),
    ('残りのカードを',                'put the rest of the cards in the '),
    ('すべてが',                      'all '),
    ('のレベル',                      "'s level "),
    ('相手は',                        'your opponent '),
    ('枚まで引き',                    ' draw up to '),
    ('枚引い',                        ' draw '),
    ('枚までを',                      ' up to '),
    ('まで発動',                      ' activates up to'),
    ('レベルより高い',                'higher than level '),
    ('レベルより低い',                'lower than level '),
    ('ステップの始めに',              'at the start of the step'),
    ('の枚数',                        'the number of '),
    ('の合計',                        'the total of '),
    ('置く。',                        'put it.'),
    ('置き',                          'put it '),
    ('次の',                          'the following '),
    ('他の',                          'other '),
    ('があり',                        ' exists and '),
    ('カードが',                      'card '),
    ('カード名に',                    'with the card name '),
    ('カードの',                      "card's "),
    ('カードを',                      'card '),

    # ── Common sentence connectors ────────────────────────────────────────────
    ('し、',                          ', '),
    ('その',                          'that '),
    ('キャラを',                      'character '),
    ('自分の',                        'your '),
    ('相手に',                        'to your opponent '),
    ('あなたが',                      'when you '),
    ('あなた',                        'you '),
    ('選び、',                        'choose, '),
    ('置かれた時、',                  'when placed, '),
    ('、',                             ', '),

    # ── "その/この" + game-term compounds (must precede bare のX patterns) ─────
    ('そのキャラを思い出にする', 'send that character to memory'),
    ('そのキャラを控え室に置く', 'put that character in the waiting room'),
    ('そのキャラを手札に戻す',   'return that character to your hand'),
    ('そのキャラを山札の上に置く', 'put that character on top of your deck'),
    ('そのキャラすべてに、',     'all of those characters '),
    ('そのキャラすべてに',       'all of those characters'),
    ('そのキャラが',             'that character '),
    ('そのキャラの',             "that character's "),
    ('そのキャラを',             'that character '),
    ('そのキャラ',               'that character'),
    ('そのカードを手札に加える', 'add that card to your hand'),
    ('そのカードを控え室に置く', 'put that card in the waiting room'),
    ('そのカードが',             'that card '),
    ('そのカードの',             "that card's "),
    ('そのカードを',             'that card '),
    ('そのカード',               'that card'),
    ('このカードとバトルしているキャラが', 'the character battling with this card '),
    ('このカードとバトルしているキャラを', 'the character battling with this card '),
    ('このカードとバトルしている', 'battling with this card'),
    ('クロックの1番上にある時、',   'is on top of your clock, '),
    ('クロックの１番上にある時、',  'is on top of your clock, '),
    ('クロックの1番上にあり、',     'is on top of your clock and '),
    ('クロックの１番上にあり、',    'is on top of your clock and '),
    ('クロックの1番上',             'on top of your clock'),
    ('クロックの１番上',            'on top of your clock'),

    # ── Misc ──────────────────────────────────────────────────────────────────
    ('このカードが',                  'this card '),
    ('このカードの',                  "this card's "),
    ('このカードを',                  'this card '),
    ('このカード',                    'this card'),
    ('公開したカードは元に戻す）',    'return the revealed card to its original place)'),
    ('（クライマックスのレベルは0として扱う', '(climax are regarded as level 0'),
    ('クライマックスのレベルは0として扱う', 'climax are regarded as level 0'),
    ('（このカードが',                '(when this card '),
    ('のレベルを',                    "'s level "),
    ('のカード名を',                  " card's name "),
    ('のカード名に',                  " with the card name "),
    ('のカード名',                    " card name"),
    ('を含むキャラを',                'character containing '),
    ('を含む',                        ' containing '),
    ('がいるなら、',                  ' exists, '),
    ('の場合、',                      'in that case, '),
    ('置場',                          ' zone'),
    ('枚数×',                         'x'),
    ('×',                             'x'),
    ('に等しい',                      ''),
    ('してよい',                      'you may '),
    ('てよい',                        'may '),
    ('する',                          ''),
]

# Pre-compile trait / name patterns for JP source
TRAIT_RE_JP = re.compile(r'《[^》]+》')
NAME_RE_JP  = re.compile(r'「[^」]{1,60}」')
MULTI_TRAIT = re.compile(r'::TRAIT::(?:\s*(?:か|or|and|と|/|・)\s*::TRAIT::)+')

# Sort JP_MAP by key length descending so longer matches always win
JP_MAP_SORTED = sorted(JP_MAP, key=lambda x: -len(x[0]))


# ── Additional standalone fragments not covered by compound phrases ───────────
# Applied as a final cleanup pass (also sorted longest-first).
JP_CLEANUP: list[tuple[str, str]] = [
    # ── Ability keywords ────────────────────────────────────────────────────
    ('応援',                        'SUPPORT'),
    ('アラーム',                    'ALARM'),
    ('助太刀',                      'BACKUP'),

    # ── Damage cancel variations ─────────────────────────────────────────────
    ('与えたダメージがキャンセルされた時',
     'when damage you deal is canceled'),
    ('ダメージがキャンセルされた時',    'when damage is canceled'),

    # ── ALARM condition: "if this card is on top of clock and your level ≥ X" ─
    ('クロックの１番上にあり、',        'is on top of your clock, '),
    ('クロックの1番上にあり、',         'is on top of your clock, '),
    ('クロックの１番上にある時、',      'when it is on top of your clock, '),
    ('クロックの1番上にある時、',       'when it is on top of your clock, '),

    # ── Battling-with patterns ────────────────────────────────────────────────
    ('とバトルしているキャラが',        'the character battling with this '),
    ('バトルしているキャラが',          'the character in battle '),
    ('バトルしているキャラを',          'the character in battle '),
    ('バトルしている',                  'in battle'),

    # ── "Cannot be chosen by effects" ────────────────────────────────────────
    ('の効果に選ばれない',              'cannot be chosen by your opponent\'s effects'),
    ('効果に選ばれない',                'cannot be chosen by effects'),
    ('効果では選ばれない',              'cannot be chosen by effects'),

    # ── Marker mechanic ───────────────────────────────────────────────────────
    ('下にマーカーとして置く',          'place it as a marker under this'),
    ('のマーカーとして置く',            'place it as a marker under'),
    ('マーカーとして置く',              'place it as a marker'),
    ('下のマーカー',                    'the marker under this'),
    ('下マーカー',                      'marker underneath'),
    ('マーカー',                        'marker'),

    # ── "Same card name" ─────────────────────────────────────────────────────
    ('同じカード名',                    'with the same card name'),

    # ── Reveal patterns ──────────────────────────────────────────────────────
    ('公開したカードは元に戻す',        'return the revealed cards to their original places'),
    ('公開したカードを',                'the revealed card '),
    ('公開して',                        'reveal it and '),
    ('公開し、',                        'reveal it, '),
    ('公開する',                        'reveal it'),
    ('公開',                            'reveal'),

    # ── Shuffle ───────────────────────────────────────────────────────────────
    ('シャッフルする',                  'shuffle'),
    ('シャッフル',                      'shuffle'),

    # ── Draw phrases ─────────────────────────────────────────────────────────
    ('枚まで引く',                      ' draw up to '),
    ('枚引く',                          ' draw '),
    ('枚引き',                          ' draw '),

    # ── "Look at top X, put in any order" ────────────────────────────────────
    ('好きな順番で山札の上に置く',      'put them on top of your deck in any order'),
    ('上好きな順番で置く',              'put them in any order on top'),
    ('上好きな順番',                    'on top in any order'),

    # ── Move-to-slot ─────────────────────────────────────────────────────────
    ('のいない枠に動かす',              'move it to an open slot'),
    ('好きな枠に動かす',                'move it to any slot'),
    ('の枠に動かす',                    'move it to the slot'),
    ('枠に動かす',                      'move it to the slot'),
    ('好きな枠に',                      'in any slot on'),

    # ── Swap / exchange ───────────────────────────────────────────────────────
    ('と入れ替える',                    'swap it with'),
    ('入れ替える',                      'swap'),
    ('入れ替え',                        'swap'),

    # ── "Among X, choose 1" ──────────────────────────────────────────────────
    ('うち1枚を',                       'among them, choose 1 '),
    ('うち',                            'among '),

    # ── Flip face-up / face-down ─────────────────────────────────────────────
    ('表向きに置く',                    'place it face up'),
    ('裏向きに置く',                    'place it face down'),
    ('裏向きにシャッフル',              'shuffle face down'),
    ('表向き',                          'face up'),
    ('裏向き',                          'face down'),

    # ── "For each of those cards" ─────────────────────────────────────────────
    ('それらのカードにクライマックスが1枚以上あるなら',
     'if there is 1 or more climax among those cards'),
    ('それらのカードに',                'among those cards '),
    ('それらのカード',                  'those cards'),
    ('それぞれに',                      'each '),
    ('それぞれ',                        'each'),
    ('それら',                          'those'),

    # ── "N times, perform" ────────────────────────────────────────────────────
    ('回行う',                          ' times'),
    ('2つの効果',                       '2 effects'),
    ('3つの効果',                       '3 effects'),

    # ── Phase names ───────────────────────────────────────────────────────────
    ('メインフェイズ',                  'main phase'),
    ('トリガーステップ',                'trigger step'),
    ('トリガーチェック',                'trigger check'),
    ('トリガーアイコン',                'trigger icon'),
    ('アンコールステップ',              'encore step'),

    # ── Attack during ─────────────────────────────────────────────────────────
    ('アタックした時',                  'when this attacks'),
    ('アタック中',                      'during the attack'),
    ('アタック',                        'attack'),

    # ── "At the start of" ────────────────────────────────────────────────────
    ('始めに',                          'at the start of'),
    ('始め',                            'start'),
    ('終わりに',                        'at the end of'),
    ('終わり',                          'end'),

    # ── Cannot use ───────────────────────────────────────────────────────────
    ('使えない',                        'cannot be used'),
    ('できない',                        'cannot'),
    ('しない',                          'does not'),
    ('いない',                          'does not exist'),

    # ── "Treat as" ───────────────────────────────────────────────────────────
    ('として扱う',                      'treat it as'),

    # ── "When X is done to this" / passive triggers ───────────────────────────
    ('を使った時',                      'when you use'),
    ('された時',                        'when it is'),
    ('た時',                            'when'),

    # ── "Gains" / "grants" ───────────────────────────────────────────────────
    ('を得る',                          'gains'),
    ('を与える',                        'deals'),

    # ── Standalone game terms ─────────────────────────────────────────────────
    ('プレイヤー',                      'player'),
    ('イベント',                        'event'),
    ('キャラクター',                    'character'),
    ('キャラがいない',                  'no characters'),
    ('キャラすべてに',                  'all characters'),
    ('キャラが',                        'characters '),
    ('すべてを',                        'all '),
    ('すべてに',                        'all '),
    ('それら',                          'those '),
    ('置かれたターン中',                'for the turn it was placed'),
    ('ストックが',                      'your stock has'),
    ('コスト',                          'cost'),
    ('中央',                            'center'),
    ('以下の',                          'or lower '),
    ('以下',                            ' or less'),
    ('以上の',                          'or higher '),
    ('以上',                            ' or more'),
    ('効果',                            'effect'),
    ('選んだ',                          'chosen'),
    ('そう',                            'if so'),

    # ── Standalone zone words (without directional particles) ─────────────────
    ('控え室',                          'waiting room'),
    ('クライマックス',                  'climax'),
    ('クロック',                        'clock'),
    ('ストック',                        'stock'),
    ('舞台',                            'stage'),
    ('手札',                            'hand'),
    ('山札',                            'deck'),
    ('カード',                          'card'),
    ('マーカー',                        'marker'),
    ('レベル',                          'Level'),
    ('バトル中',                        'in battle'),
    ('バトル',                          'battle'),
    ('ターン中',                        'for the turn'),

    # ── Standalone pronouns/reference words ───────────────────────────────────
    ('自分',                            'your'),
    ('相手',                            "your opponent's"),
    ('この',                            'this '),
    ('その',                            'that '),
    ('それ',                            'it'),
    ('ない',                            'not'),
    ('ある',                            'exists'),

    # ── Punctuation / brackets still in JP form ───────────────────────────────
    ('。',                              '. '),
    ('（',                              '('),
    ('）',                              ')'),
    ('『',                              '"'),
    ('』',                              '"'),
    ('「',                              '"'),
    ('」',                              '"'),
    ('・',                              '/'),

    # ── Marker under patterns ────────────────────────────────────────────────
    ('の下にマーカーとして置く',        "place it as a marker under this card"),
    ('の下にマーカーとして',            "as a marker under this card"),
    ('下にマーカーとして置く',          'place it as a marker under this'),
    ('下にマーカーとして',              'as a marker under this'),
    ('の下に置く',                      'place it under this card'),
    ('下に置く',                        'place it under'),
    ('下に',                            'under '),
    ('下の',                            'under '),
    ('下',                              'under'),

    # ── Keyword abilities not yet covered ─────────────────────────────────────
    ('大活躍',                          'GRAND PLAY'),
    ('かわりに',                        'instead, '),

    # ── "Rearrange in any order" ─────────────────────────────────────────────
    ('好きな順番で並べ直す',            'rearrange in any order'),
    ('好きな順番で',                    'in any order '),
    ('並べ直す',                        'rearrange'),
    ('並べ',                            'arrange'),
    ('並',                              'arrange'),
    ('直す',                            'restore'),

    # ── Common kanji terms ───────────────────────────────────────────────────
    ('能力を使',                        'use ability'),
    ('能力',                            'ability'),
    ('好',                              'any'),

    # ── Katakana phase names not yet covered ─────────────────────────────────
    ('スタンドフェイズ',                'stand phase'),
    ('クロックフェイズ',                'clock phase'),
    ('レベルアップ',                    'level up'),

    # ── Common kanji counters / positional ────────────────────────────────────
    ('番上',                            'on top'),
    ('枚見て',                          ' cards, look at'),
    ('枚見',                            ' cards, look at'),
    ('枚',                              ' cards'),
    ('時、',                            ' when '),
    ('時',                              ' when'),
    ('置く',                            'place it'),
    ('置い',                            'placed'),
    ('置',                              'place'),
    ('表向き',                          'face up'),
    ('裏向き',                          'face down'),
    ('上',                              'top'),
    ('回',                              ' times'),

    # ── Single hiragana particles — last resort, after all compounds consumed ──
    # These appear between already-translated English words; map to space.
    ('の',                              ' '),
    ('が',                              ' '),
    ('は',                              ' '),
    ('を',                              ' '),
    ('に',                              ' '),
    ('も',                              ' '),
    ('と',                              ' '),
    ('か',                              ' '),
    ('て',                              ' '),
    ('で',                              ' '),
    ('し',                              ' '),
    ('ず',                              ' '),
    ('ら',                              ' '),
    ('り',                              ' '),
    ('き',                              ' '),
    ('く',                              ' '),
    ('い',                              ' '),
    ('う',                              ' '),
    ('る',                              ' '),
    ('た',                              ' '),
    ('ん',                              ' '),
    ('な',                              ' '),
    ('ま',                              ' '),
    ('み',                              ' '),
    ('む',                              ' '),
    ('も',                              ' '),
    ('や',                              ' '),
    ('ゆ',                              ' '),
    ('よ',                              ' '),
    ('わ',                              ' '),
    ('れ',                              ' '),
    ('ち',                              ' '),
    ('つ',                              ' '),
    ('め',                              ' '),
    ('ぞ',                              ' '),
    ('ぜ',                              ' '),
    ('け',                              ' '),
    ('ば',                              ' '),
    ('び',                              ' '),
    ('ぶ',                              ' '),
    ('べ',                              ' '),
    ('ぼ',                              ' '),
    ('ぱ',                              ' '),
    ('ぴ',                              ' '),
    ('ぷ',                              ' '),
    ('ぺ',                              ' '),
    ('ぽ',                              ' '),
    ('ぎ',                              ' '),
    ('ぐ',                              ' '),
    ('げ',                              ' '),
    ('ご',                              ' '),
    ('ざ',                              ' '),
    ('じ',                              ' '),
    ('ぞ',                              ' '),
    ('だ',                              ' '),
    ('ぢ',                              ' '),
    ('づ',                              ' '),
    ('で',                              ' '),
    ('ど',                              ' '),
    ('お',                              ' '),
    ('あ',                              ' '),
    ('え',                              ' '),
    ('ぁ',                              ' '),
    ('ぃ',                              ' '),
    ('ぅ',                              ' '),
    ('ぇ',                              ' '),
    ('ぉ',                              ' '),
    ('ょ',                              ' '),
    ('ゅ',                              ' '),
    ('ゃ',                              ' '),
    ('っ',                              ' '),
    ('ー',                              ' '),
]

JP_CLEANUP_SORTED = sorted(JP_CLEANUP, key=lambda x: -len(x[0]))


# ── Translation function ─────────────────────────────────────────────────────

def translate_jp(text: str) -> str:
    """JP raw text → English, using hand-crafted map + learned key."""
    if not text:
        return text
    result = text

    # Step 0: replace traits 《…》 and names 「…」 with placeholders
    result = TRAIT_RE_JP.sub('::TRAIT::', result)
    result = NAME_RE_JP.sub('[CHARACTER]', result)
    result = MULTI_TRAIT.sub('::TRAIT::', result)

    # Step 1: hand-crafted phrase table, longest-first
    for jp, en in JP_MAP_SORTED:
        if jp in result:
            result = result.replace(jp, en)

    # Step 2: learned phrase map (sorted longest first at load time)
    for jp, en in LEARNED_SORTED:
        if jp in result:
            result = result.replace(jp, en)

    # Step 3: cleanup standalone fragments not caught above
    for jp, en in JP_CLEANUP_SORTED:
        if jp in result:
            result = result.replace(jp, en)

    return result.strip()


# ── Normalisation (applies to ALL cards after translation) ───────────────────

CXCOMBO_RE = re.compile(r'CXコンボ|CXCombo|CXCOMBO|\bCX\s+COMBO\b', re.I)

# Trait patterns in both JP 《》 and EN <<>> notation
TRAIT_RE_ALL = re.compile(r'《[^》]+》|<<[^>]+>>')
# JP card name brackets 「」 and broken variants
JP_NAME_RE   = re.compile(r'「[^」]{1,60}」')
JP_NAME_BRKN = re.compile(r'「[^」"]{1,60}"')
# EN card names in quotes — Title Case strings with capitals
EN_NAME_RE   = re.compile(r'"([A-Z][A-Za-z\',!\?\-\s]{3,80})"')

_COMMON_WORDS = {
    'the','a','an','of','in','on','at','to','for','with','and','or','is',
    'are','this','that','your','you','if','when','may','can','do','not',
    'all','its','it','be','by','as','so','up','no','into','from',
}

def _is_card_name(s: str) -> bool:
    words = s.split()
    if not words:
        return False
    common_ratio = sum(1 for w in words if w.lower() in _COMMON_WORDS) / len(words)
    if common_ratio > 0.4:
        return False
    caps = sum(1 for w in words if w and w[0].isupper())
    return caps >= 1 and len(words) <= 8

def fw_to_hw(text: str) -> str:
    """Fullwidth ASCII → halfwidth, plus common special chars."""
    result = []
    for ch in text:
        cp = ord(ch)
        if 0xFF01 <= cp <= 0xFF5E:
            result.append(chr(cp - 0xFEE0))
        elif ch == '＋': result.append('+')
        elif ch == '－': result.append('-')
        elif ch == '　': result.append(' ')
        else: result.append(ch)
    return ''.join(result)

# Ability marker bracket conversions (JP fullwidth → EN halfwidth)
# Specific forms first, then a general 【X】 → [X] fallback
_BRACKET_SUBS = [
    ('【CX COMBO】',   'CX COMBO'),
    ('【CXコンボ】',   'CX COMBO'),
    ('【AUTO】',       '[AUTO]'),
    ('【CONT】',       '[CONT]'),
    ('【ACT】',        '[ACT]'),
    ('【COUNTER】',    '[COUNTER]'),
    ('【自】',         '[AUTO]'),
    ('【永】',         '[CONT]'),
    ('【起】',         '[ACT]'),
    ('【カウンター】', '[COUNTER]'),
]
# Fallback regex for any remaining 【X】 forms
_BRACKET_FALLBACK = re.compile(r'【([^】]+)】')

TERM_SUBS: list[tuple] = [
    (CXCOMBO_RE,                         'CX COMBO'),
    (re.compile(r'\bLibrary\b'),         'deck'),
    (re.compile(r'\bThis card\b'),       'this card'),
    (re.compile(r'\bCHARACTER\b'),       'character'),
    (re.compile(r'\bキャラ\b'),          'character'),
    (re.compile(r'\bCLOCK\b'),          'clock'),
    (re.compile(r'\bClock\b'),          'clock'),
    (re.compile(r'\bMemory\b'),         'memory'),
    (re.compile(r'\bSTOCK\b'),          'stock'),
    (re.compile(r'\bLevel(\d)\b'),       r'Level \1'),
    (re.compile(r'  +'),                 ' '),
    (re.compile(r' ([.,)）\]])'),        r'\1'),
]

def normalize(text: str, apply_trait_norm: bool = False) -> str:
    if not text:
        return text
    # Convert JP ability markers to EN bracket form
    for jp, en in _BRACKET_SUBS:
        if jp in text:
            text = text.replace(jp, en)
    # Fallback: any remaining 【X】 → [X]
    text = _BRACKET_FALLBACK.sub(r'[\1]', text)
    text = fw_to_hw(text)
    if apply_trait_norm:
        # Replace trait markers 《》 and <<>> with ::TRAIT::
        text = TRAIT_RE_ALL.sub('::TRAIT::', text)
        # Collapse multi-trait (::TRAIT:: or ::TRAIT::) → ::TRAIT::
        text = MULTI_TRAIT.sub('::TRAIT::', text)
        # Replace JP quoted names
        text = JP_NAME_BRKN.sub('[CHARACTER]', text)
        text = JP_NAME_RE.sub('[CHARACTER]', text)
        # Replace EN quoted card names
        def _repl(m: re.Match) -> str:
            return '[CHARACTER]' if _is_card_name(m.group(1)) else m.group(0)
        text = EN_NAME_RE.sub(_repl, text)
    for pat, repl in TERM_SUBS:
        text = pat.sub(repl, text)
    return text.strip()


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ── JP cards: retranslate from card_text_jp_raw ───────────────────────────
    c.execute("""
        SELECT card_no, card_text_jp_raw
        FROM cards
        WHERE lang='jp' AND card_text_jp_raw IS NOT NULL AND card_text_jp_raw != ''
    """)
    jp_rows = c.fetchall()
    print(f'JP cards to retranslate: {len(jp_rows):,}')

    jp_updated = 0
    for card_no, jp_raw in jp_rows:
        new_en = translate_jp(jp_raw)
        new_en = normalize(new_en, apply_trait_norm=False)  # trait norm already done in translate_jp
        if not DRY_RUN:
            conn.execute("UPDATE cards SET card_text_en=? WHERE card_no=?", (new_en, card_no))
        jp_updated += 1

    if not DRY_RUN:
        conn.commit()
    print(f'JP retranslated: {jp_updated:,}')

    # ── EN cards: re-normalize from card_text_en_raw ──────────────────────────
    c.execute("""
        SELECT card_no, card_text_en_raw
        FROM cards
        WHERE lang='en' AND card_text_en_raw IS NOT NULL AND card_text_en_raw != ''
    """)
    en_rows = c.fetchall()
    print(f'EN cards to normalize: {len(en_rows):,}')

    en_updated = 0
    for card_no, en_raw in en_rows:
        new_en = normalize(en_raw, apply_trait_norm=True)
        if not DRY_RUN:
            conn.execute("UPDATE cards SET card_text_en=? WHERE card_no=?", (new_en, card_no))
        en_updated += 1

    if not DRY_RUN:
        conn.commit()
    print(f'EN normalized: {en_updated:,}')

    conn.close()

    # ── Quality report ────────────────────────────────────────────────────────
    print('\n=== Quality Report ===')
    conn2 = sqlite3.connect(DB_PATH)
    c2 = conn2.cursor()

    c2.execute("SELECT card_text_en FROM cards WHERE lang='jp' AND card_text_en IS NOT NULL")
    jp_texts = [r[0] for r in c2.fetchall() if r[0]]
    jp_hiragana = sum(1 for t in jp_texts if re.search(r'[ぁ-ん]', t))
    jp_katakana  = sum(1 for t in jp_texts if re.search(r'[ァ-ン]', t))
    jp_kanji     = sum(1 for t in jp_texts if re.search(r'[一-鿿]', t))
    jp_blank     = sum(1 for t in jp_texts if not t.strip())
    print(f'JP cards with EN text  : {len(jp_texts):,}')
    print(f'  still has hiragana   : {jp_hiragana:,} ({100*jp_hiragana/max(1,len(jp_texts)):.1f}%)')
    print(f'  still has katakana   : {jp_katakana:,} ({100*jp_katakana/max(1,len(jp_texts)):.1f}%)')
    print(f'  still has kanji      : {jp_kanji:,}  ({100*jp_kanji/max(1,len(jp_texts)):.1f}%)')
    print(f'  blank after translate: {jp_blank:,}')

    c2.execute("SELECT COUNT(*) FROM cards WHERE lang='jp' AND (card_text_en IS NULL OR card_text_en='')")
    print(f'JP cards with no EN    : {c2.fetchone()[0]:,}')

    # Sample well-translated card
    print('\nSample JP cards (hand→stage trigger):')
    c2.execute("""
        SELECT card_no, card_text_en
        FROM cards WHERE lang='jp' AND card_text_en LIKE '%placed on the stage from your hand%'
        LIMIT 3
    """)
    for r in c2.fetchall():
        print(f'  [{r[0]}] {r[1][:140]}')

    # Sample remaining problem cards
    print('\nSample cards with remaining hiragana:')
    c2.execute("SELECT card_no, card_text_en FROM cards WHERE lang='jp' AND card_text_en IS NOT NULL LIMIT 5000")
    samples = [(r[0], r[1]) for r in c2.fetchall() if r[1] and re.search(r'[ぁ-ん]', r[1])][:5]
    for cn, t in samples:
        print(f'  [{cn}] {t[:140]}')

    conn2.close()


if __name__ == '__main__':
    main()
