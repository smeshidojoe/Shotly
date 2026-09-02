"""
Окно «О программе».
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..core.constants import APP_NAME, APP_VERSION, DEVELOPER_URL, GITHUB_REPO
from ..core.i18n import tr
from . import icons, theme
from .widgets import Window

REPO_URL = "https://github.com/%s" % GITHUB_REPO


class AboutWindow(Window):
    def __init__(self, parent=None):
        super().__init__(tr("About"), parent)
        self.setFixedWidth(theme.s(380))

        root = QVBoxLayout(self)
        root.setContentsMargins(theme.s(18), self.title_h + theme.s(16),
                                theme.s(18), theme.s(16))
        root.setSpacing(theme.s(10))

        head = QHBoxLayout()
        head.setSpacing(theme.s(14))
        logo = QLabel(self)
        side = theme.s(64)
        logo.setPixmap(icons.app_icon().pixmap(side, side))
        logo.setFixedSize(side, side)
        head.addWidget(logo, 0, Qt.AlignTop)

        titles = QVBoxLayout()
        titles.setSpacing(theme.s(2))
        name = QLabel("%s %s" % (APP_NAME, APP_VERSION), self)
        name.setStyleSheet("font-size: %dpx; font-weight: 600;" % theme.s(18))
        titles.addWidget(name)
        desc = QLabel(tr("A screenshot tool: select, draw, copy, save."), self)
        desc.setProperty("dim", True)
        desc.setWordWrap(True)
        titles.addWidget(desc)
        head.addLayout(titles, 1)
        root.addLayout(head)

        link = QLabel(
            '<a style="color:%s; text-decoration:none;" href="%s">%s</a>'
            % (theme.PALETTE["accent"], REPO_URL, tr("Project page")), self)
        link.setOpenExternalLinks(True)
        root.addWidget(link)

        author = QLabel(
            '<span style="color:%s;">© 2026 </span>'
            '<a style="color:%s; text-decoration:none;" href="%s">SmeshidoJoe</a>'
            % (theme.PALETTE["text_dim"], theme.PALETTE["accent"], DEVELOPER_URL),
            self)
        author.setOpenExternalLinks(True)
        root.addWidget(author)

        root.addSpacing(theme.s(4))
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton(tr("Close"), self)
        close.setProperty("accent", True)
        close.clicked.connect(self.close)
        row.addWidget(close)
        root.addLayout(row)

        self.adjustSize()
        self.setFixedHeight(self.sizeHint().height())
