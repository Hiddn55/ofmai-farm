"""A Reel is of the niche by its author or by its caption, read from the tree
(warming-policy.md §7 bis, days 8-14); anything else is swiped past."""

from gitd.farm import niche

REEL = (
    '<hierarchy><node content-desc="Reel by Whitney Simmons, 12,304 likes, 96 comments, September 20" bounds="[0,0][720,1200]"/>'
    '<node resource-id="com.instagram.android:id/clips_username" text="whitneyysimmons" bounds="[40,1100][300,1140]"/>'
    '<node text="leg day is the best day #gymgirl #legday" bounds="[40,1150][700,1200]"/>'
    '<node content-desc="Like" bounds="[640,900][700,960]"/></hierarchy>'
)
OTHER = (
    '<hierarchy><node content-desc="Reel by Cat Videos Daily, 1,204 likes" bounds="[0,0][720,1200]"/>'
    '<node text="he did it again lol" bounds="[40,1150][700,1200]"/></hierarchy>'
)
NICHE = ["@gymshark", "#gymgirl", "workout", "legday", "fitcheck"]


def test_the_author_is_read_from_the_labels():
    assert niche.author_of(REEL) == "whitney simmons"
    assert niche.author_of('<node content-desc="benfrancis posted a video September 14"/>') == "benfrancis"
    assert niche.author_of(OTHER) == "cat videos daily"


def test_a_known_author_is_of_the_niche_whatever_the_caption():
    v = niche.judge(REEL, handles={"whitney simmons"}, terms=set())
    assert v.niche and v.reason == "author"


def test_the_caption_decides_when_the_author_is_unknown():
    terms = niche.niche_terms(NICHE)
    assert terms == {"gymgirl", "workout", "legday", "fitcheck"}
    v = niche.judge(REEL, handles=set(), terms=terms)
    assert v.niche and v.reason == "caption"
    assert niche.judge(OTHER, handles=set(), terms=terms).niche is False


def test_one_stray_word_is_not_the_niche_but_one_hashtag_is():
    terms = {"workout", "day"}
    stray = '<hierarchy><node text="what a day" bounds="[0,0][1,1]"/></hierarchy>'
    assert niche.judge(stray, handles=set(), terms=terms).niche is False
    tagged = '<hierarchy><node text="what a #workout" bounds="[0,0][1,1]"/></hierarchy>'
    assert niche.judge(tagged, handles=set(), terms=terms).niche is True


def test_handles_come_from_the_at_entries_and_the_discovered_list():
    assert niche.niche_handles(NICHE, extra=["fitfam_jess"]) == {"gymshark", "fitfam_jess"}
