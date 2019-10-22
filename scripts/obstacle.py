#!/usr/bin/env python
# -*- coding: utf-8 -*-

import rospy
from geometry_msgs.msg import Twist
import message_filters
from sensor_msgs.msg import Image,CameraInfo, NavSatFix
from cv_bridge import CvBridge, CvBridgeError
from costmap_converter.msg import ObstacleArrayMsg, ObstacleMsg
from visualization_msgs.msg import Marker, MarkerArray
from geometry_msgs.msg import Point32
import numpy as np
from darknet_ros_msgs.msg import BoundingBoxes,BoundingBox
from nav_msgs.msg import Odometry
from apriltags2_ros.msg import AprilTagDetection, AprilTagDetectionArray
from geometry_msgs.msg import PoseWithCovarianceStamped, Pose
import tf
import cv2
import math


class Publishsers():
    def __init__(self):
        # Publisherを作成
        self.publisher = rospy.Publisher('/move_base/TebLocalPlannerROS/obstacles', ObstacleArrayMsg, queue_size=1)
        self.marker_publisher = rospy.Publisher("/visualized_obstacle", MarkerArray, queue_size = 1)
        self.landmark_publisher = rospy.Publisher("/rtabmap/tag_detections", AprilTagDetectionArray, queue_size = 1)
        self.gnss_publisher = rospy.Publisher("/rtabmap/global_pose", PoseWithCovarianceStamped, queue_size = 1)
        self.obstacle_list = ["landmark"]
        self.tf_br = tf.TransformBroadcaster()
        self.tf_listener = tf.TransformListener()
        self.obstacle_msg = ObstacleArrayMsg() 
        self.marker_data = MarkerArray()
        self.landmark_msg = AprilTagDetectionArray()
        self.odom = Odometry()
        self.start = PoseWithCovarianceStamped()
        self.position = PoseWithCovarianceStamped()
        self.now = rospy.get_rostime()
        self.prev = rospy.get_rostime()

    def make_msg(self, Depth1Image, Depth2Image, detection_data, camera1_param, camera2_param, odom, start):
        bboxes_from_camera1 = BoundingBoxes()
        bboxes_from_camera2 = BoundingBoxes()
        bboxes_from_camera1.header = Depth1Image.header
        bboxes_from_camera2.header = Depth2Image.header
        self.odom = odom
        self.start = start
        self.now = rospy.get_rostime()
        self.timebefore = detection_data.header.stamp
        # Add point obstacle
        self.obstacle_msg.header.stamp = detection_data.header.stamp
        self.obstacle_msg.header.frame_id = "odom" # CHANGE HERE: odom/map
        #opencvに変換
        bridge = CvBridge()
        try:
            Depth1image = bridge.imgmsg_to_cv2(Depth1Image, desired_encoding="passthrough")
            Depth2image = bridge.imgmsg_to_cv2(Depth2Image, desired_encoding="passthrough")
            for bbox in detection_data.bounding_boxes:
                if (bbox.xmax - bbox.xmin) > 50 and (bbox.ymax - bbox.ymin) > 50:
                    tmp_box = BoundingBox()
                    tmp_box.Class = bbox.Class
                    tmp_box.probability = bbox.probability
                    tmp_box.xmin = bbox.xmin
                    tmp_box.xmax = bbox.xmax
                    tmp_box.ymin = bbox.ymin
                    tmp_box.ymax = bbox.ymax
                    if (tmp_box.ymin + bbox.ymax)/2 < Depth1image.shape[0]:
                        if tmp_box.ymax > Depth1image.shape[0]:
                            tmp_box.ymax = Depth1image.shape[0]
                        bboxes_from_camera1.bounding_boxes.append(tmp_box)
                    elif  (bbox.ymin + bbox.ymax)/2 > Depth1image.shape[0]:
                        tmp_box.ymin = bbox.ymin - Depth1image.shape[0]
                        tmp_box.ymax = bbox.ymax - Depth1image.shape[0]
                        if bbox.ymin < 0:
                            tmp_box.ymin = 0
                        bboxes_from_camera2.bounding_boxes.append(tmp_box)
            camera1_obstacle_msg, camera2_obstacle_msg = ObstacleArrayMsg(), ObstacleArrayMsg()
            camera1_marker_data, camera2_marker_data = MarkerArray(), MarkerArray()
            camera1_obstacle_msg, camera1_marker_data = self.bbox_to_position_in_odom(bboxes_from_camera1, Depth1image, camera1_param)
            obstacle_msg, marker_data = self.bbox_to_position_in_odom(bboxes_from_camera2, Depth2image, camera2_param, len(camera1_obstacle_msg.obstacles), camera1_obstacle_msg, camera1_marker_data)
            self.obstacle_msg.obstacles, self.marker_data.markers = self.update_obstacles(self.obstacle_msg, obstacle_msg, self.marker_data, marker_data)
        except CvBridgeError as e:
            pass

    def send_msg(self):
        self.publisher.publish(self.obstacle_msg)
        self.gnss_publisher.publish(self.position)
        self.marker_publisher.publish(self.marker_data)
    
    def bbox_to_position_in_odom(self, bboxes, DepthImage, camera_param, i=0, obstacle_msg=ObstacleArrayMsg(), marker_data=MarkerArray()):
        j = 0
        self.position = PoseWithCovarianceStamped()
        self.marker_data = MarkerArray()
        if i == 0:
            del obstacle_msg.obstacles[:]
            del marker_data.markers[:]
        for bbox in bboxes.bounding_boxes:
            if bbox.Class in self.obstacle_list:
                try:
                    tan_angle_x = camera_param[0][0]*(bbox.xmin+bbox.xmax)/2+camera_param[0][1]*(bbox.ymin+bbox.ymax)/2+camera_param[0][2]*1 
                    angle_x = math.atan(tan_angle_x)
                    if 0 < abs(math.degrees(angle_x)) < 35:
                        detected_area = DepthImage[bbox.ymin:bbox.ymax, bbox.xmin:bbox.xmax]
                        detected_area = np.where(detected_area > 8.0, detected_area, np.nan)
                        distance_x = np.nanmedian(detected_area)/1000
                        distance_x = distance_x
                        distance_y = - distance_x * tan_angle_x
                        if 2.0 < distance_x < 6.0:
                            now = rospy.Time.now()
                            obstacle_msg.obstacles.append(ObstacleMsg())
                            marker_data.markers.append(Marker())
                            self.tf_br.sendTransform((-distance_y, 0, distance_x), tf.transformations.quaternion_from_euler(0, 0, 0), rospy.Time.now(), bbox.Class + str(i), bboxes.header.frame_id)
                            self.tf_listener.waitForTransform("/odom", "/" + bbox.Class + str(i), rospy.Time(0), rospy.Duration(0.1))
                            obstable_position = self.tf_listener.lookupTransform("/odom", "/" + bbox.Class + str(i), now)
                            obstacle_msg.obstacles[i].header.stamp, obstacle_msg.obstacles[i].header.frame_id = bboxes.header.stamp, "odom"    
                            obstacle_msg.obstacles[i].id = i
                            obstacle_msg.obstacles[i].polygon.points = [Point32()]
                            obstacle_msg.obstacles[i].polygon.points[0].x = obstable_position[0][0]
                            obstacle_msg.obstacles[i].polygon.points[0].y = obstable_position[0][1]
                            obstacle_msg.obstacles[i].polygon.points[0].z = obstable_position[0][2]
                            marker_data.markers[i].header.stamp, marker_data.markers[i].header.frame_id = bboxes.header.stamp, "odom"     
                            marker_data.markers[i].ns, marker_data.markers[i].id = "obstacle", i
                            marker_data.markers[i].action = Marker.ADD
                            marker_data.markers[i].pose.position.x, marker_data.markers[i].pose.position.y, marker_data.markers[i].pose.position.z = obstable_position[0][0], obstable_position[0][1], obstable_position[0][2]
                            marker_data.markers[i].pose.orientation.x, marker_data.markers[i].pose.orientation.y, marker_data.markers[i].pose.orientation.z, marker_data.markers[i].pose.orientation.w= tf.transformations.quaternion_from_euler(0, 0, 0) 
                            marker_data.markers[i].color.r, marker_data.markers[i].color.g, marker_data.markers[i].color.b, marker_data.markers[i].color.a = 0, 1, 0, 1
                            marker_data.markers[i].scale.x, marker_data.markers[i].scale.y, marker_data.markers[i].scale.z = 0.2, 0.2, 1
                            marker_data.markers[i].type = 3
                            i = i + 1
                except Exception as e:
                    pass
        return obstacle_msg, marker_data

    def update_obstacles(self, prev_obstacle_msg, detected_obstacle_msg, prev_marker_msg, marker_msg):
        self.tf_listener.waitForTransform("/odom", "/base_link", rospy.Time(0), rospy.Duration(0.1))
        current_position = self.tf_listener.lookupTransform("/odom", "/base_link",  rospy.Time(0))
        for detected_obstacle, marker in zip(detected_obstacle_msg.obstacles, marker_msg.markers): 
            updated = False
            print("OK")
            for prev_obstacle, prev_marker in zip(prev_obstacle_msg.obstacles, prev_marker_msg.markers):        
                if abs(current_position[0][0] - prev_obstacle.polygon.points[0].x) > 4 or abs(current_position[0][1] - prev_obstacle.polygon.points[0].y) > 4:
                    prev_obstacle_msg.obstacles.pop(prev_obstacle)
                    prev_marker_msg.markers.pop(prev_marker)  
                    break                                    
                if ((detected_obstacle.polygon.points[0].x - prev_obstacle.polygon.points[0].x) * (detected_obstacle.polygon.points[0].x - prev_obstacle.polygon.points[0].x) + (detected_obstacle.polygon.points[0].y - prev_obstacle.polygon.points[0].y) * (detected_obstacle.polygon.points[0].y - prev_obstacle.polygon.points[0].y)) < 1:
                    prev_obstacle.polygon.points[0].x = detected_obstacle.polygon.points[0].x 
                    prev_obstacle.polygon.points[0].y = detected_obstacle.polygon.points[0].y
                    print(prev_marker.pose.position.x)
                    prev_marker.pose.position.x = marker.pose.position.x 
                    print(prev_marker.pose.position.x)
                    prev_marker.pose.position.y = marker.pose.position.y
                    updated = True                  
                break
            if not updated:
                prev_obstacle_msg.obstacles.append(detected_obstacle)                    
                prev_marker_msg.markers.append(marker)                    
        return prev_obstacle_msg.obstacles, prev_marker_msg.markers

class Subscribe_publishers():
    def __init__(self, pub):
        self.depth1_subscriber = message_filters.Subscriber('/camera1/aligned_depth_to_color/image_raw', Image)
        self.depth2_subscriber = message_filters.Subscriber('/camera2/aligned_depth_to_color/image_raw', Image)
        self.detection_subscriber =message_filters.Subscriber("/darknet_ros/bounding_boxes", BoundingBoxes)
        self.odom_subscriber = message_filters.Subscriber('/odometry/filtered', Odometry)
        self.camera1_param_subscriber = rospy.Subscriber("/camera1/color/camera_info", CameraInfo, self.camera1_parameter_callback)
        self.camera2_param_subscriber = rospy.Subscriber("/camera2/color/camera_info", CameraInfo, self.camera2_parameter_callback)
        self.start_subscriber = rospy.Subscriber('/gnss_odom', Odometry, self.gnss_start_callback)

        # messageの型を作成
        self.pub = pub
        self.depth1_image = Image()
        self.depth2_image = Image()
        self.detection_data = BoundingBoxes()
        self.camera1_parameter = CameraInfo()
        self.camera2_parameter = CameraInfo()
        self.odom = Odometry()
        self.start_position = PoseWithCovarianceStamped()
        ts = message_filters.ApproximateTimeSynchronizer([self.depth1_subscriber, self.depth2_subscriber, self.detection_subscriber, self.odom_subscriber], 10, 0.05)
        ts.registerCallback(self.bounding_boxes_callback)

    def camera1_parameter_callback(self, data):
        camera_parameter_org = data.K
        camera_parameter_org = np.reshape(camera_parameter_org, (3, 3))
        self.camera1_parameter = np.linalg.inv(camera_parameter_org)
        print ("Camera parameter:")
        print (camera_parameter_org)
        self.camera1_param_subscriber.unregister()

    def camera2_parameter_callback(self, data):
        camera_parameter_org = data.K
        camera_parameter_org = np.reshape(camera_parameter_org, (3, 3))
        self.camera2_parameter = np.linalg.inv(camera_parameter_org)
        print ("Camera parameter:")
        print (camera_parameter_org)
        self.camera2_param_subscriber.unregister() 

    def gnss_start_callback(self, Odom):
        if Odom.header.seq == 23872:
            start = Odom
            start.header.frame_id = "base_link"
            self.start_position.pose.pose.position.x = start.pose.pose.position.x
            self.start_position.pose.pose.position.y = start.pose.pose.position.y
            self.start_position.pose.pose.orientation = start.pose.pose.orientation
            print ("start_x:" + str(start.pose.pose.position.x))
            print ("start_y:" + str(start.pose.pose.position.y))
            self.start_subscriber.unregister() 

    def odom_callback(self, Odom):
        self.odom = Odometry()

    def bounding_boxes_callback(self, depth1_image, depth2_image, detection_data, odom):
        self.depth1_image, self.depth2_image, self.detection_data, self.odom = depth1_image, depth2_image, detection_data, odom

    def pub_msg(self):
        self.pub.make_msg(self.depth1_image, self.depth2_image, self.detection_data, self.camera1_parameter, self.camera2_parameter, self.odom, self.start_position)
        self.pub.send_msg()

def main():
    # nodeの立ち上げ
    rospy.init_node('obstacle')

    # クラスの作成
    pub = Publishsers()
    sub = Subscribe_publishers(pub)
    rospy.sleep(1)
    while not rospy.is_shutdown():
        sub.pub_msg()

if __name__ == '__main__':
    main()
