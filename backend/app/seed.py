"""Create a demo user and a sample course with a plain-text material, then run the
Course Brain pipeline synchronously so the MVP is immediately usable.
Usage: python -m app.seed
"""
import os

from app.database import SessionLocal, init_db
from app import models
from app.core.config import settings
from app.services import course_brain, course_service, scoring
from app.services.material_service import create_material

SAMPLE = """# 计算机网络期末复习重点

## 第一章 网络基础

OSI七层模型：物理层、数据链路层、网络层、传输层、会话层、表示层、应用层。
TCP/IP体系结构与OSI模型的对应关系是高频考点。

## 第二章 物理层

数据通信基础：码元、波特率、比特率。
信道的极限容量：奈奎斯特准则与香农公式。

## 第三章 数据链路层

1. 封装成帧的作用是什么？
A. 差错控制
B. 流量控制
C. 保证帧的完整性
D. 提高传输效率
2. 以太网的CSMA/CD协议原理。

## 第四章 网络层

IP地址的分类与子网划分。
ARP协议的作用是把IP地址解析为MAC地址。
路由选择协议：RIP与OSPF的区别。

1. 什么是IP地址？它与MAC地址有什么区别？
2. 子网掩码的作用是什么？

## 第五章 传输层

TCP三次握手的过程与为什么需要三次握手。
TCP四次挥手过程。
UDP与TCP的区别。

1. TCP建立连接为什么需要三次握手而不是两次？
2. TCP与UDP分别适用于什么场景？

## 第六章 应用层

HTTP协议特点与工作过程。
DNS域名解析过程。
"""


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        user = course_service.get_or_create_user(db, settings.demo_user_id)
        course = course_service.create_course(
            db,
            user,
            {
                "name": "计算机网络",
                "school": "示例大学",
                "teacher": "张老师",
                "exam_date": "2026-08-28",
                "preferences": {"learning_mode": "EXPLANATION_FIRST", "simulation_mode": "OPTIONAL"},
            },
        )
        os.makedirs("data/materials", exist_ok=True)
        path = "data/materials/sample_computer_network.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(SAMPLE)

        material = models.Material(
            course_id=course.id,
            type="TEXTBOOK",
            source="upload",
            name="计算机网络复习重点.txt",
            file_path=os.path.abspath(path),
            status="PENDING",
        )
        db.add(material)
        db.flush()
        course_brain.process_material(db, material)
        scoring.score_study_units(db, course)
        course.status = "READY"
        db.commit()

        units = db.query(models.StudyUnit).filter(models.StudyUnit.course_id == course.id).count()
        questions = db.query(models.Question).filter(models.Question.course_id == course.id).count()
        print(f"Seeded: course={course.id} units={units} questions={questions} status={course.status}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
