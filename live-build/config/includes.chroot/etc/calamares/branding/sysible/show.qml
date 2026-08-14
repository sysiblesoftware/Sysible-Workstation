/* Sysible Workstation install slideshow — branded, multi-slide.
   Highlights the baked-in toolchain, SysTerm, and Sysible Controller while the
   install runs. slideshowAPI 2. */
import QtQuick 2.0;
import calamares.slideshow 1.0;

Presentation {
    id: presentation

    function nextSlide() { presentation.goToNextSlide(); }

    Timer {
        interval: 7000
        running: true
        repeat: true
        onTriggered: nextSlide()
    }

    // ---- Slide 1: welcome + mark ------------------------------------------
    Slide {
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#0d1117" }
                GradientStop { position: 1.0; color: "#11161f" }
            }
            Column {
                anchors.centerIn: parent
                spacing: 18
                width: parent.width * 0.8
                Image {
                    anchors.horizontalCenter: parent.horizontalCenter
                    source: "mark.png"
                    width: 108; height: 117
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    color: "#e8eefc"; font.pixelSize: 30; font.bold: true
                    text: "Welcome to Sysible Workstation"
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    horizontalAlignment: Text.AlignHCenter
                    color: "#93a1b8"; font.pixelSize: 17
                    text: "The engineering & automation workstation.\nSit tight — we're setting things up. It won't take long."
                }
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 190; height: 4; radius: 2
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: "#6ddb73" }
                        GradientStop { position: 1.0; color: "#5580ee" }
                    }
                }
            }
        }
    }

    // ---- Slide 2: the toolchain -------------------------------------------
    Slide {
        Rectangle {
            anchors.fill: parent; color: "#0d1117"
            Column {
                anchors.centerIn: parent; spacing: 14; width: parent.width * 0.82
                Text { color: "#5cc746"; font.pixelSize: 13; font.bold: true
                       text: "YOUR WHOLE TOOLCHAIN, BAKED IN" }
                Text { color: "#e8eefc"; font.pixelSize: 27; font.bold: true
                       text: "Install it and start working" }
                Text { width: parent.width; wrapMode: Text.WordWrap
                       color: "#a7b4cc"; font.pixelSize: 17; lineHeight: 1.35
                       text: "• Docker & Kubernetes (kubectl, helm, k9s)\n"
                           + "• Terraform / OpenTofu, Packer, Ansible\n"
                           + "• AWS, Azure & Google Cloud CLIs\n"
                           + "• VS Code, Git, and the SysTerm terminal" }
                Text { color: "#6f7d94"; font.pixelSize: 14
                       text: "No post-install setup — it's all ready the moment you boot." }
            }
        }
    }

    // ---- Slide 3: SysTerm --------------------------------------------------
    Slide {
        Rectangle {
            anchors.fill: parent; color: "#0d1117"
            Column {
                anchors.centerIn: parent; spacing: 14; width: parent.width * 0.82
                Text { color: "#5cc746"; font.pixelSize: 13; font.bold: true
                       text: "MEET SYSTERM" }
                Text { color: "#e8eefc"; font.pixelSize: 27; font.bold: true
                       text: "The terminal built for Sysible" }
                Text { width: parent.width; wrapMode: Text.WordWrap
                       color: "#a7b4cc"; font.pixelSize: 17; lineHeight: 1.35
                       text: "• Ctrl+Shift+N opens a fresh window\n"
                           + "• Broadcast mode types to every tab at once — an amber\n"
                           + "   frame reminds you it's armed\n"
                           + "• Right-click any folder in Files → Open in SysTerm" }
                Text { color: "#6f7d94"; font.pixelSize: 14
                       text: "It's your default terminal everywhere in the desktop." }
            }
        }
    }

    // ---- Slide 4: Sysible Controller --------------------------------------
    Slide {
        Rectangle {
            anchors.fill: parent; color: "#0d1117"
            Column {
                anchors.centerIn: parent; spacing: 14; width: parent.width * 0.82
                Text { color: "#5cc746"; font.pixelSize: 13; font.bold: true
                       text: "SYSIBLE CONTROLLER" }
                Text { color: "#e8eefc"; font.pixelSize: 27; font.bold: true
                       text: "Run your whole fleet from one console" }
                Text { width: parent.width; wrapMode: Text.WordWrap
                       color: "#a7b4cc"; font.pixelSize: 17; lineHeight: 1.35
                       text: "Manage every Linux host — users, health, services, packages,\n"
                           + "storage, networking and firewall — plus live terminals, over\n"
                           + "the lightweight agent or straight over SSH. No DSL, no\n"
                           + "control repo, no apply step. Just buttons." }
                Text { color: "#6f7d94"; font.pixelSize: 14
                       text: "Launch \"Install Sysible Controller CE\" from the desktop after setup." }
            }
        }
    }

    // ---- Slide 5: almost there --------------------------------------------
    Slide {
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#11161f" }
                GradientStop { position: 1.0; color: "#0d1117" }
            }
            Column {
                anchors.centerIn: parent; spacing: 16; width: parent.width * 0.8
                Text { anchors.horizontalCenter: parent.horizontalCenter
                       color: "#e8eefc"; font.pixelSize: 27; font.bold: true
                       text: "Almost there…" }
                Text { anchors.horizontalCenter: parent.horizontalCenter
                       horizontalAlignment: Text.AlignHCenter
                       width: parent.width; wrapMode: Text.WordWrap
                       color: "#a7b4cc"; font.pixelSize: 17; lineHeight: 1.35
                       text: "Tip: in Sysible Controller, the dashboard search box finds any\n"
                           + "action by name — \"create a user\", \"open a firewall port\" — and\n"
                           + "jumps straight to the right tool." }
                Text { anchors.horizontalCenter: parent.horizontalCenter
                       color: "#5580ee"; font.pixelSize: 15
                       text: "Docs & guides:  sysible.com/controller" }
            }
        }
    }
}
