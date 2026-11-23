import math
import unittest

from review_preflight import check_switch_sites, select_switch_site


class SwitchSitesTest(unittest.TestCase):
    def setUp(self):
        def space(use, left, right, entries, dry=True):
            return dict(use=use, dry=dry, entries=entries,
                        boundary=[[left, 0], [right, 0], [right, 3000], [left, 3000]])

        self.floor = dict(
            spaces={"hall": space("hall", -2000, 0, []),
                    "bed": space("bedroom", 0, 3000, [["hall", "entry"]]),
                    "bath": space("bathroom", 3000, 5000, [["bed", "ensuite"]], False)},
            access={"entry": dict(kind="door", between=["hall", "bed"], point=[0, 950]),
                    "ensuite": dict(kind="door", between=["bed", "bath"], point=[3000, 950]),
                    "nightstand": dict(kind="cabinet", space="bed", point=[1600, 0])},
            spans=[dict(wall="partition", at=["ensuite"], space="bath", ends=[[3000, 960], [3000, 1900]]),
                   dict(wall="entry-wall", at=["entry"], space="bed", ends=[[0, 1000], [0, 2000]]),
                   dict(wall="partition", at=["ensuite"], space="bed", ends=[[3000, 960], [3000, 1900]]),
                   dict(wall="headboard", at=["nightstand"], space="bed", ends=[[1450, 0], [1750, 0]])],
            lampSpaces={"L": "bed", "B": "bath"}, sheetOrigins={"E1": [1000, 5000]})
        self.intent = dict(role="entry", route=["hall", "bed"], access="entry", width=100, lights=["L"])
        d = dict(id="S", sheet="E1", floor=1, kind="DUAL", room="卧室", p=[0, 1050],
                 normal=0, switchIntent=self.intent)
        self.package = dict(switchSpaces={"1": self.floor}, devices=[d],
                            edges=[dict(role="control", fromId="S", toId="L")],
                            jobs=[dict(op="copy", layer="EQUIP-开关", tag="dev-E1-S", p=[1000,6050])])

    def test_bedroom_entry_and_actual_insert(self):
        check_switch_sites(self.package)
        self.package["jobs"][0]["p"][0] += 150
        with self.assertRaisesRegex(ValueError, "插块"):
            check_switch_sites(self.package)

    def test_ensuite_cannot_be_used_as_bedroom_entry(self):
        self.intent.update(route=["bath", "bed"], access="ensuite")
        with self.assertRaisesRegex(ValueError, "日常操作入口"):
            select_switch_site(self.floor, self.intent)

    def test_bathroom_switch_on_dry_side_despite_nearer_wet_face(self):
        self.intent.update(route=["hall", "bed", "bath"], access="ensuite", lights=["B"])
        site = select_switch_site(self.floor, self.intent)
        self.assertEqual(site["space"], "bed")
        self.assertAlmostEqual(math.cos(site["normal"]), -1)

    def test_no_room_for_panel_does_not_fall_back_to_other_room(self):
        self.floor["spans"][1]["ends"] = [[0,1000],[0,1050]]
        with self.assertRaisesRegex(ValueError, "待定"):
            select_switch_site(self.floor, self.intent)

    def test_bedside_uses_cabinet_and_shared_panel_rejects_wet_side(self):
        self.intent.update(role="bedside", route=["bed"], access="nightstand")
        self.assertEqual(select_switch_site(self.floor, self.intent)["p"], [1600, 0])
        self.intent.update(role="shared", route=["bed", "bath"], access="ensuite", lights=["B"],
                           operateIn="bath", reason="两组在门口操作")
        with self.assertRaisesRegex(ValueError, "干区"):
            select_switch_site(self.floor, self.intent)

    def test_shared_dry_panel_checks_both_lamp_groups(self):
        self.intent.update(role="shared", route=["bed", "bath"], access="ensuite",
                           lights=["L", "B"], operateIn="bed", reason="同一干区门口操作")
        # This is not the bedroom's main entrance: its main light cannot be assigned here.
        self.floor["spaces"]["bed"]["entries"] = [["hall", "entry"]]
        self.package["edges"].append(dict(role="control", fromId="S", toId="B"))
        self.package["devices"][0].update(p=[3000, 1010], normal=math.pi)
        self.package["jobs"][0]["p"] = [4000, 6010]
        with self.assertRaisesRegex(ValueError, "卧室入口"):
            check_switch_sites(self.package)
        self.floor["spaces"]["bed"]["use"] = "wardrobe"
        check_switch_sites(self.package)

    def test_reject_cross_room_point_and_missing_inputs(self):
        self.package["devices"][0]["p"] = [3000, 1010]
        with self.assertRaisesRegex(ValueError, "偏离"):
            check_switch_sites(self.package)
        del self.package["switchSpaces"]
        with self.assertRaisesRegex(ValueError, "缺少"):
            check_switch_sites(self.package)


if __name__ == "__main__":
    unittest.main()
