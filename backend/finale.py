"""The five endings as scenes. The words that frame each ending are fixed; the villagers who speak, and what they
say, come from this run. Nothing here names a past event that did not happen."""
# offer: what the village does when it gathers (never the ending's name). open and close: narration around the
# villagers' lines. gather: the tone the model is given. fallback: the line used if the model cannot speak.
ENDINGS = {
    "names_we_buried": {
        "title": "The Names We Buried",
        "tint": "#1b1410",
        "offer": "There is a truth the village has been carrying through the cold. They are waiting to see "
                 "whether you will say it.",
        "open": ["The snow stops at the edge of the square, as if it were waiting.",
                 "Everyone is here. No one speaks first, and no one looks away."],
        "gather": "a hard truth has been said aloud in the square and cannot be taken back",
        "close": ["Some of what was buried comes up with the thaw. It is heavier than anyone had guessed.",
                  "You said it, and the village is clearer for it. Something that cannot be replaced went out "
                  "of the room with the words."],
        "fallback": "You said what the rest of us would not.",
    },
    "last_place_at_the_table": {
        "title": "The Last Place at the Table",
        "tint": "#2a1f14",
        "offer": "The little that is left has been laid out on one table. The village is waiting to see whether "
                 "you will sit down with them.",
        "open": ["The tables are pushed together in the square. There is less bread than there are people.",
                 "Someone sets a place, and nobody asks who it is for."],
        "gather": "there is less food than there are people and the village has sat down together anyway",
        "close": ["Not everyone is fed, and everyone knows it. They eat slowly, looking at one another.",
                  "You gave something up so that the table could stay a table. In spring the village will still be "
                  "here, thinner and closer."],
        "fallback": "There was a place for you, and you kept it for someone else.",
    },
    "the_peace_you_made": {
        "title": "The Peace You Made",
        "tint": "#1d2a22",
        "offer": "The village has a settlement in front of it that could hold. They are waiting to see whether you "
                 "will put your name to it.",
        "open": ["The square is quiet in a way it has not been since you arrived.",
                 "Terms have been agreed. Hands are shaken that would rather not be."],
        "gather": "a settlement has been agreed that will hold, and not everyone is easy about what it rests on",
        "close": ["The winter is survivable, and ordinary days begin again. They are better days than before.",
                  "A few people are paying for them. Everyone knows who, and they have agreed not to say."],
        "fallback": "It holds. I try not to look at what it rests on.",
    },
    "the_last_departure": {
        "title": "The Last Departure",
        "tint": "#121a28",
        "offer": "The road out of the village is open. They are waiting to see whether you will take it.",
        "open": ["The road out of Bellwether is only a line in the snow.",
                 "Someone stands at the edge of the square. They do not ask you to stay for any reason that "
                 "would help."],
        "gather": "the newcomer is about to leave the village for good, and you would rather they stayed",
        "close": ["You go anyway. The village behind you grows small and does not stop being lit.",
                  "It will have a spring. You will not be in it, and you will not know what it meant."],
        "fallback": "Stay, if you like. Nobody needs you to. I would only like it.",
    },
    "the_end_of_all_things": {
        "title": "The End of All Things",
        "tint": "#050505",
        "offer": "Something under the square has begun to turn, and the village has stopped arguing with it. "
                 "They are waiting to see whether you will let it.",
        "open": ["The cold has stopped feeling like weather.",
                 "Under the square something old turns over, and every promise that was ever broken is "
                 "suddenly very loud."],
        "gather": "something old has begun to turn under the square and the village has stopped fighting it",
        "close": ["Someone you trusted says your name as if it were a question. You do not answer.",
                  "The lights go out house by house. Nobody is left to remember that they were lit."],
        "fallback": "I keep thinking there must have been another way.",
    },
}

SPEAKERS = 3


def speakers(conn, player: str, villagers: list[str]) -> list[str]:
    """The villagers who carry the most of this run: weighted by how much they remember of the player."""
    rows = conn.execute("select npc_id, sum(severity) s from memories where player=? group by npc_id "
                        "order by s desc, npc_id", (player,)).fetchall()
    ranked = [r["npc_id"] for r in rows if r["npc_id"] in villagers]
    return (ranked + [v for v in villagers if v not in ranked])[:SPEAKERS]


def slides(ending: str, lines: list[tuple[str, str]]) -> list[dict]:
    """Narration, then each villager's line, then narration, then the closing title card."""
    e = ENDINGS[ending]
    return ([{"kind": "narration", "text": t} for t in e["open"]]
            + [{"kind": "line", "who": who, "text": text} for who, text in lines]
            + [{"kind": "narration", "text": t} for t in e["close"]]
            + [{"kind": "title", "text": e["title"]}])
