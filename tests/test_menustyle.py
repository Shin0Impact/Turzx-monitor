from turingscreen import menustyle

TPM_BOTTOMALIGN = 0x0020
TPM_RETURNCMD = 0x0100


def test_menu_opens_with_its_left_edge_at_the_cursor():
    flags = menustyle.TPM_RIGHTALIGN | TPM_BOTTOMALIGN | TPM_RETURNCMD
    assert menustyle.open_right(flags) == TPM_BOTTOMALIGN | TPM_RETURNCMD


def test_other_flags_are_untouched():
    assert menustyle.open_right(TPM_RETURNCMD) == TPM_RETURNCMD


def test_does_nothing_off_windows():
    menustyle.apply()  # would raise on Linux if it tried to load uxtheme
