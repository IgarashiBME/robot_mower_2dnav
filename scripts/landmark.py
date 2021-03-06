#!/usr/bin/env python
# -*- coding: utf-8 -*-

import rospy
from geometry_msgs.msg import Twist
import message_filters
from sensor_msgs.msg import Image,CameraInfo
from cv_bridge import CvBridge, CvBridgeError
from costmap_converter.msg import ObstacleArrayMsg, ObstacleMsg
from visualization_msgs.msg import Marker, MarkerArray
from geometry_msgs.msg import Point32
import numpy as np
from darknet_ros_msgs.msg import BoundingBoxes,BoundingBox
from rtabmap_ros.srv import ResetPose
from apriltags2_ros.msg import AprilTagDetection, AprilTagDetectionArray
import tf
import cv2
import math


class Publishsers():
    def __init__(self):
        # Publisherを作成
        self.publisher = rospy.Publisher('/move_base/TebLocalPlannerROS/obstacles', ObstacleArrayMsg, queue_size=1)
        self.marker_publisher = rospy.Publisher("/visualized_obstacle", MarkerArray, queue_size = 1)
        self.landmark_publisher = rospy.Publisher("/rtabmap/tag_detections", AprilTagDetectionArray, queue_size = 1)
        self.obstacle_list = ["person"]
        self.tf_br = tf.TransformBroadcaster()
        self.tf_listener = tf.TransformListener()
        self.obstacle_msg = ObstacleArrayMsg() 
        self.marker_data = MarkerArray()
        self.landmark_msg = AprilTagDetectionArray()
        self.now = rospy.get_rostime()
        self.prev = rospy.get_rostime()

    def make_msg(self, Depth1Image, Depth2Image, detection_data, camera1_param, camera2_param):
        bboxes_from_camera1 = BoundingBoxes()
        bboxes_from_camera2 = BoundingBoxes()
        bboxes_from_camera1.header = Depth1Image.header
        bboxes_from_camera2.header = Depth2Image.header
        self.now = rospy.get_rostime()
        self.timebefore = detection_data.header.stamp
        # Add point obstacle
        #self.obstacle_msg = ObstacleArrayMsg() 
        self.obstacle_msg.header.stamp = detection_data.header.stamp
        self.obstacle_msg.header.frame_id = "odom" # CHANGE HERE: odom/map
        #self.marker_data = MarkerArray()
        self.landmark_msg = AprilTagDetectionArray()
        self.landmark_msg.detections.append(AprilTagDetection())
        self.landmark_msg.header.stamp = detection_data.header.stamp
        #opencvに変換
        bridge = CvBridge()
        try:
            Depth1image = bridge.imgmsg_to_cv2(Depth1Image, desired_encoding="passthrough")
            Depth2image = bridge.imgmsg_to_cv2(Depth2Image, desired_encoding="passthrough")
        except CvBridgeError as e:
            print(e)
        for bbox in detection_data.bounding_boxes:
            if (bbox.ymin + bbox.ymax)/2 < Depth1image.shape[0]:
                if bbox.ymax > Depth1image.shape[0]:
                    bbox.ymax = Depth1image.shape[0]
                bboxes_from_camera1.bounding_boxes.append(bbox)
            else:
                bbox.ymin = bbox.ymin - Depth1image.shape[0]
                bbox.ymax = bbox.ymax - Depth1image.shape[0]
                if bbox.ymin < 0:
                    bbox.ymin = 0
                bboxes_from_camera2.bounding_boxes.append(bbox)
        camera1_obstacle_msg, camera2_obstacle_msg = ObstacleArrayMsg(), ObstacleArrayMsg()
        camera1_landmark_msg, camera2_landmark_msg = AprilTagDetectionArray(), AprilTagDetectionArray()
        camera1_marker_data, camera2_marker_data = MarkerArray(), MarkerArray()
        camera1_obstacle_msg, camera1_marker_data = self.bbox_to_position_in_odom(bboxes_from_camera1, Depth1image, camera1_param)
        obstacle_msg, marker_data = self.bbox_to_position_in_odom(bboxes_from_camera2, Depth2image, camera2_param, len(camera1_obstacle_msg.obstacles), camera1_obstacle_msg, camera1_marker_data)
        
    def send_msg(self):
        self.publisher.publish(self.obstacle_msg)
        self.marker_publisher.publish(self.marker_data)      
    
    def bbox_to_position_in_odom(self, bboxes, DepthImage, camera_param, i=0, obstacle_msg=ObstacleArrayMsg(), marker_data=MarkerArray()):
        if i == 0:
            del obstacle_msg.obstacles[:]
            del marker_data.markers[:]
        self.landmark_msg.header.stamp = bboxes.header.stamp
        self.landmark_msg.header.frame_id = "base_link"
        for bbox in bboxes.bounding_boxes:
            if bbox.Class in self.obstacle_list:
                tan_angle_x = camera_param[0][0]*(bbox.xmin+bbox.xmax)/2+camera_param[0][1]*(bbox.ymin+bbox.ymax)/2+camera_param[0][2]*1 
                angle_x = math.atan(tan_angle_x)
                if abs(math.degrees(angle_x)) < 35:
                    detected_area = DepthImage[bbox.ymin:bbox.ymax,  bbox.xmin:bbox.xmax]
                    distance_x = np.median(detected_area)/1000
                    distance_x = distance_x + 0.15
                    if bboxes.header.frame_id == "camera2_color_optical_frame":
                        distance_x = - distance_x
                    distance_y = - distance_x * tan_angle_x
                    if 1.0 < distance_x < 3.0:
                        self.tf_br.sendTransform((-distance_y, 0, distance_x), tf.transformations.quaternion_from_euler(0, 0, 0), rospy.Time.now(),bbox.Class ,bboxes.header.frame_id)
                        self.tf_listener.waitForTransform("/base_link", "/" + bbox.Class, rospy.Time(0), rospy.Duration(0.1))
                        landmark_position = self.tf_listener.lookupTransform("/base_link", bboxes.header.frame_id, rospy.Time(0))
                        self.landmark_msg.detections[0].id = [1]
                        self.landmark_msg.detections[0].size = [0.3]
                        self.landmark_msg.detections[0].pose.header = bboxes.header
                        self.landmark_msg.detections[0].pose.header.frame_id = bbox.Class
                        self.landmark_msg.detections[0].pose.pose.pose.position.x = landmark_position[0][0]
                        self.landmark_msg.detections[0].pose.pose.pose.position.y = landmark_position[0][1]
                        self.landmark_msg.detections[0].pose.pose.pose.position.z = landmark_position[0][2]
                        self.landmark_msg.detections[0].pose.pose.covariance = [(self.landmark_msg.detections[0].pose.pose.pose.position.x*0.01) * (self.landmark_msg.detections[0].pose.pose.pose.position.x*0.01), 0.0 ,0.0, 0.0, 0.0 ,0.0, 0.0, 9999, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, (self.landmark_msg.detections[0].pose.pose.pose.position.z*0.01) * (self.landmark_msg.detections[0].pose.pose.pose.position.z*0.01) ,0.0, 0.0, 0.0, 0.0, 0.0 ,0.0, 9999.0, 0.0 ,0.0, 0.0, 0.0, 0.0, 0.0, 9999.0, 0.0, 0.0, 0.0, 0.0 ,0.0, 0.0, 9999]
                        self.landmark_publisher.publish(self.landmark_msg)    
        return obstacle_msg, marker_data

    def update_obstacles(self, prev_obstacle_msg, detected_obstacle_msg, prev_marker_msg, marker_msg):
        self.tf_listener.waitForTransform("/odom", "/base_link", rospy.Time(0), rospy.Duration(0.1))
        current_position = self.tf_listener.lookupTransform("/odom", "/base_link",  rospy.Time(0))
        for detected_obstacle, marker in zip(detected_obstacle_msg.obstacles, marker_msg.markers): 
            updated = False
            for prev_obstacle, prev_marker in zip(prev_obstacle_msg.obstacles, prev_marker_msg.markers):        
                if abs(current_position[0][0] - prev_obstacle.polygon.points[0].x) > 4 or abs(current_position[0][1] - prev_obstacle.polygon.points[0].y) > 4:
                    prev_obstacle_msg.obstacles.pop(prev_obstacle)
                    prev_marker_msg.markers.pop(prev_marker)  
                    break                                    
                if ((detected_obstacle.polygon.points[0].x - prev_obstacle.polygon.points[0].x) * (detected_obstacle.polygon.points[0].x - prev_obstacle.polygon.points[0].x) + (detected_obstacle.polygon.points[0].y - prev_obstacle.polygon.points[0].y) * (detected_obstacle.polygon.points[0].y - prev_obstacle.polygon.points[0].y)) ** 0.5 < 1.0:
                    prev_obstacle.polygon.points[0].x = detected_obstacle.polygon.points[0].x 
                    prev_obstacle.polygon.points[0].y = detected_obstacle.polygon.points[0].y
                    prev_marker.pose.position.x = marker.pose.position.x 
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
        self.camera1_param_subscriber = rospy.Subscriber("/camera1/color/camera_info", CameraInfo, self.camera1_parameter_callback)
        self.camera2_param_subscriber = rospy.Subscriber("/camera2/color/camera_info", CameraInfo, self.camera2_parameter_callback)
        # messageの型を作成
        self.pub = pub
        self.camera1_parameter = CameraInfo()
        self.camera2_parameter = CameraInfo()
        ts = message_filters.ApproximateTimeSynchronizer([self.depth1_subscriber, self.depth2_subscriber, self.detection_subscriber], 10, 0.05)
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

    def bounding_boxes_callback(self, depth1_image, depth2_image, detection_data):
        self.pub.make_msg(depth1_image, depth2_image, detection_data, self.camera1_parameter, self.camera2_parameter)
        self.pub.send_msg()

def main():
    # nodeの立ち上げ
    rospy.init_node('publish_tree')

    # クラスの作成
    pub = Publishsers()
    sub = Subscribe_publishers(pub)

    rospy.spin()

if __name__ == '__main__':
    main()
