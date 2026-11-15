from django.test import SimpleTestCase

from marketplace.management.commands.calibrate_embeddings import auc, match_threshold, rates

# (score, is_positive): positives at 0.9/0.7/0.5, negatives at 0.6/0.3/0.1.
PAIRS = [(0.9, True), (0.7, True), (0.5, True), (0.6, False), (0.3, False), (0.1, False)]


class CalibrationMathTests(SimpleTestCase):
    def test_rates_count_scores_at_or_above_the_cutoff(self):
        self.assertEqual(rates(PAIRS, 0.5), {"recall": 1.0, "fpr": round(1 / 3, 4)})
        self.assertEqual(rates(PAIRS, 0.65), {"recall": round(2 / 3, 4), "fpr": 0.0})

    def test_recall_match_picks_the_strictest_cutoff_that_keeps_recall(self):
        self.assertEqual(match_threshold(PAIRS, "recall", 1.0), 0.5)
        self.assertEqual(match_threshold(PAIRS, "recall", round(2 / 3, 4)), 0.7)

    def test_fpr_match_picks_the_loosest_cutoff_that_keeps_false_positives(self):
        self.assertEqual(match_threshold(PAIRS, "fpr", 0.0), 0.605)
        self.assertEqual(match_threshold(PAIRS, "fpr", round(1 / 3, 4)), 0.305)

    def test_auc_counts_positive_wins_and_half_ties(self):
        # Positive 0.5 loses only to negative 0.6: 8 of 9 comparisons won.
        self.assertEqual(auc(PAIRS), round(8 / 9, 4))
        self.assertEqual(auc([(0.5, True), (0.5, False)]), 0.5)


class ManualThresholdOptionTests(SimpleTestCase):
    def test_set_option_parses_names_and_rejects_bad_input(self):
        from django.core.management.base import CommandError

        from marketplace.management.commands.calibrate_embeddings import Command

        command = Command()
        self.assertEqual(command._parse_manual(["search=0.62", "gate=0.6449"]),
                         {"search": 0.62, "gate": 0.645})
        for bad in (["nope=0.5"], ["search=high"]):
            with self.subTest(bad=bad), self.assertRaises(CommandError):
                command._parse_manual(bad)
