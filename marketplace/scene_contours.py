"""Hand-traced silhouettes in the reference images' native 1024px coordinates.

Bounds only position the SVG; they are never drawn. Closed subpaths describe
visible furniture parts and, with evenodd fill, the openings between table legs.
Keep these coordinates tied to the unmodified square scene images.
"""

CONTOURS = {
    "rocking-chair.png": {
        "bounds": (694, 568, 246, 250),
        "path": (
            "M 826 575 Q 871 584 934 580 "
            "L 923 625 Q 917 650 908 672 "
            "Q 907 678 912 693 L 924 763 "
            "Q 929 779 913 789 Q 869 817 820 802 "
            "L 799 785 Q 744 792 709 778 "
            "Q 695 774 703 755 L 726 680 "
            "Q 730 654 747 653 L 776 660 "
            "L 811 633 Z "
            "M 737 721 L 790 735 L 780 758 "
            "Q 750 771 721 763 Z "
            "M 834 740 L 893 750 L 911 776 "
            "Q 869 800 824 788 Z"
        ),
        "label_x": 52,
        "label_bottom": 35,
    },
    "coffee-table.png": {
        "bounds": (413, 705, 188, 168),
        "path": (
            "M 435 711 L 582 711 L 595 739 L 597 867 "
            "L 419 867 L 418 740 Z "
            "M 434 757 L 581 757 L 583 806 L 433 806 Z "
            "M 432 818 L 584 818 L 587 853 L 431 853 Z"
        ),
        "label_x": 50,
        "label_bottom": 64,
    },
    "gray-pillow.png": {
        "bounds": (168, 592, 117, 96),
        "path": (
            "M 175 604 Q 209 613 248 600 "
            "Q 258 625 276 659 Q 280 665 271 669 "
            "Q 236 678 200 682 Q 186 650 175 604 Z"
        ),
        "label_x": 50,
        "label_bottom": 24,
    },
    "oak-desk.png": {
        "bounds": (256, 588, 405, 302),
        "path": (
            "M 263 613 L 310 595 L 640 595 L 654 613 "
            "L 653 641 L 632 641 Q 632 625 620 627 "
            "L 568 637 L 439 650 L 286 650 "
            "L 283 879 L 265 883 L 267 622 Z "
            "M 641 649 L 653 649 L 653 810 L 641 814 Z"
        ),
        "label_x": 19,
        "label_bottom": 76,
    },
    "desk-lamp.png": {
        "bounds": (305, 414, 134, 191),
        "path": (
            "M 395 424 Q 403 419 410 423 L 431 462 "
            "Q 424 469 412 472 L 399 446 "
            "L 323 481 L 337 582 L 338 587 "
            "L 358 588 Q 366 589 368 594 "
            "L 367 599 L 312 600 L 311 594 "
            "Q 312 589 328 588 L 315 486 "
            "Q 311 478 319 475 L 395 438 Z"
        ),
        "label_x": 60,
        "label_bottom": 17,
    },
    "bookshelf.png": {
        "bounds": (637, 570, 258, 287),
        "path": (
            "M 646 576 L 879 582 L 889 814 L 878 818 "
            "L 876 845 L 863 845 L 863 830 "
            "L 664 831 L 663 850 L 651 850 "
            "L 650 830 L 643 825 Z"
        ),
        "label_x": 50,
        "label_bottom": 22,
    },
}


def contour_geometry(asset):
    contour = CONTOURS[asset]
    x, y, width, height = contour["bounds"]
    return {
        "x": x / 1024 * 100,
        "y": y / 1024 * 100,
        "w": width / 1024 * 100,
        "h": height / 1024 * 100,
        "view_box": f"{x} {y} {width} {height}",
        "outline": contour["path"],
        "label_x": contour["label_x"],
        "label_bottom": contour["label_bottom"],
    }
